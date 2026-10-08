"""Experiment config: one YAML per experiment, reproduces any README number."""
from __future__ import annotations
import os
from pathlib import Path
import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]
def _load_dotenv(path: Path) -> None:
    """Tiny .env loader (no dependency); real environment variables win."""
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.split(" #")[0].split("\t#")[0]            # strip inline comments
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip().strip('"\''))


_load_dotenv(ROOT / ".env")
DB_PATH = ROOT / "data/db/olist.duckdb"
SCHEMA_YAML = ROOT / "schema/schema.yaml"
GLOSSARY_YAML = ROOT / "schema/glossary.yaml"
KEYWORDS_YAML = ROOT / "schema/glossary_keywords.yaml"
FEWSHOT_POOL = ROOT / "prompts/fewshot_pool.jsonl"
LLM_CACHE_DIR = Path(os.environ.get("T2S_CACHE_DIR", ROOT / ".cache/llm"))


class AgentConfig(BaseModel):
    name: str = "default"
    # model
    provider: str = "groq"            # groq | gemini | ollama | openai_compat | mock
    model: str = "openai/gpt-oss-120b"
    temperature: float = 0.0
    price_in_per_mtok: float = 0.0    # USD per 1M input tokens (use the equivalent paid-tier price on free tiers)
    price_out_per_mtok: float = 0.0
    # prompt layers (experiment ladder switches)
    descriptions: bool = True         # column/table descriptions + join paths
    samples: bool = True              # enum sample values
    glossary: bool = True
    fewshot_k: int = 3
    fewshot_mode: str = "retrieved"   # retrieved | static
    pruning: bool = False
    # loop + guardrails
    max_retries: int = 2
    guardrails: bool = True           # validator + input guard + plan check
    # runtime limits
    dialect: str = "duckdb"
    max_rows: int = 1000
    timeout_s: float = 10.0
    max_question_chars: int = 500
    history_turns: int = 3

    @classmethod
    def load(cls, path: str | Path) -> "AgentConfig":
        return cls(**yaml.safe_load(Path(path).read_text()))
