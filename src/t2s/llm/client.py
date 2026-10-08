"""Provider-agnostic LLM wrapper: retries, timeouts, JSON mode, disk cache, fallback provider."""
from __future__ import annotations
import hashlib, json, os, time
from dataclasses import dataclass
from typing import Callable, Protocol
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..utils.config import AgentConfig, LLM_CACHE_DIR


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    cached: bool = False


class LLM(Protocol):
    def complete(self, system: str, user: str, json_mode: bool = True) -> LLMResponse: ...


class CacheMiss(RuntimeError): ...
class RateLimited(RuntimeError): ...

BASES = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "ollama": (os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"), "OLLAMA_API_KEY"),
    "openai_compat": (os.environ.get("OPENAI_BASE_URL", ""), "OPENAI_API_KEY"),
}


class OpenAICompatClient:
    """Groq, Gemini (OpenAI-compat endpoint), Ollama and any OpenAI-compatible server."""

    def __init__(self, provider: str, model: str, temperature: float = 0.0, timeout_s: float = 90):
        if provider not in BASES:
            raise ValueError(f"unknown provider {provider}")
        self.base, key_env = BASES[provider]
        self.key = os.environ.get(key_env, "")
        self.provider, self.model, self.temperature, self.timeout = provider, model, temperature, timeout_s
        if provider != "ollama" and not self.key:
            raise RuntimeError(f"{key_env} not set (see .env.example)")

    @retry(retry=retry_if_exception_type((RateLimited, requests.ConnectionError, requests.Timeout)),
           wait=wait_exponential(multiplier=2, max=30), stop=stop_after_attempt(5), reraise=True)
    def complete(self, system: str, user: str, json_mode: bool = True) -> LLMResponse:
        body = {"model": self.model, "temperature": self.temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        t0 = time.time()
        r = requests.post(f"{self.base}/chat/completions", json=body, timeout=self.timeout,
                          headers={"Authorization": f"Bearer {self.key}"} if self.key else {})
        if r.status_code in (429, 500, 502, 503):
            raise RateLimited(f"{r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        d = r.json()
        u = d.get("usage") or {}
        return LLMResponse(d["choices"][0]["message"]["content"] or "", u.get("prompt_tokens", 0),
                           u.get("completion_tokens", 0), time.time() - t0)


class CachedLLM:
    """diskcache keyed by hash(prompt + model + params): reproducible evals, saves free-tier quota."""

    def __init__(self, inner: LLM | None, key_prefix: str, cache_only: bool = False, directory=LLM_CACHE_DIR):
        import diskcache
        self.inner, self.prefix, self.cache_only = inner, key_prefix, cache_only
        self.cache = diskcache.Cache(str(directory))

    def complete(self, system: str, user: str, json_mode: bool = True) -> LLMResponse:
        key = hashlib.sha256(json.dumps([self.prefix, system, user, json_mode]).encode()).hexdigest()
        hit = self.cache.get(key)
        if hit is not None:
            return LLMResponse(**{**hit, "cached": True})
        if self.cache_only or self.inner is None:
            raise CacheMiss("no cached response for this prompt")
        resp = self.inner.complete(system, user, json_mode)
        self.cache.set(key, {k: getattr(resp, k) for k in ("text", "prompt_tokens", "completion_tokens", "latency_s")})
        return resp


class FallbackLLM:
    def __init__(self, *clients: LLM):
        self.clients = clients

    def complete(self, system, user, json_mode=True):
        last = None
        for c in self.clients:
            try:
                return c.complete(system, user, json_mode)
            except Exception as e:  # noqa: BLE001 - any provider failure -> next provider
                last = e
        raise last


class CallableLLM:
    """Wrap `fn(system, user) -> str` (tests, oracle runs, canned responses)."""

    def __init__(self, fn: Callable[[str, str], str]):
        self.fn = fn

    def complete(self, system, user, json_mode=True):
        t0 = time.time()
        text = self.fn(system, user)
        return LLMResponse(text, (len(system) + len(user)) // 4, len(text) // 4, time.time() - t0)


def make_llm(cfg: AgentConfig, cache: bool = True, cache_only: bool = False, fallback: str | None = None) -> LLM:
    """Build the configured client. `fallback` = 'provider:model' used when the primary fails."""
    inner: LLM | None = None
    if not cache_only:
        inner = OpenAICompatClient(cfg.provider, cfg.model, cfg.temperature)
        if fallback:
            p, m = fallback.split(":", 1)
            inner = FallbackLLM(inner, OpenAICompatClient(p, m, cfg.temperature))
    if cache or cache_only:
        return CachedLLM(inner, f"{cfg.provider}|{cfg.model}|{cfg.temperature}", cache_only)
    return inner
