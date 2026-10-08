"""Shared request handling for the FastAPI app and the Streamlit UI (in-process mode)."""
from __future__ import annotations
import json, os, threading, time
from collections import OrderedDict, defaultdict
from pathlib import Path

import pandas as pd

from ..agent.pipeline import Agent, AgentResult
from ..explain.explain import explain
from ..guardrails.executor import execute_readonly
from ..guardrails.validator import SQLValidationError, validate_and_rewrite
from ..utils.config import ROOT, AgentConfig
from ..agent.dataset import Dataset, UploadError, cleanup_old, create_dataset
from ..viz.chart import available_kinds, choose_chart, make_figure, normalize_df

SAMPLES_PATH = ROOT / "prompts/sample_questions.json"


def load_samples() -> list[dict]:
    return json.loads(SAMPLES_PATH.read_text()) if SAMPLES_PATH.exists() else []


class AskService:
    """live mode: a configured LLM generates SQL. demo mode (no API key): only curated sample questions are
    answered, with pre-written SQL that still goes through the validator and read-only executor."""

    def __init__(self, config_path: str | None = None, with_explanation: bool = True):
        self.cfg = AgentConfig.load(config_path or os.environ.get("T2S_CONFIG", ROOT / "configs/best.yaml"))
        self.llm, self.mode = None, "demo"
        try:
            from ..llm.client import make_llm
            self.llm = make_llm(self.cfg, cache=True)
            self.mode = "live"
        except Exception:  # noqa: BLE001 - missing key etc.
            pass
        self.agent = Agent(self.cfg, self.llm) if self.llm else Agent(self.cfg, _NoLLM())
        self.with_explanation = with_explanation and self.mode == "live"
        self.history: dict[str, list[dict]] = defaultdict(list)
        self.samples = {s["question"]: s for s in load_samples()}
        self._day, self._count, self._lock = time.strftime("%Y-%m-%d"), 0, threading.Lock()
        self.daily_cap = int(os.environ.get("T2S_DAILY_CAP", "500"))
        self.datasets: "OrderedDict[str, Dataset]" = OrderedDict()
        self._ds_agents: dict[str, Agent] = {}
        self.max_datasets = int(os.environ.get("T2S_MAX_DATASETS", "20"))
        cleanup_old()

    # -- uploaded data -------------------------------------------------------------------------
    def create_dataset(self, files: list[tuple[str, bytes]], name: str | None = None) -> dict:
        ds = create_dataset(files, name)               # raises UploadError with a readable message
        self.datasets[ds.id] = ds
        while len(self.datasets) > self.max_datasets:  # evict the oldest upload
            old_id, old = self.datasets.popitem(last=False)
            self._ds_agents.pop(old_id, None)
            old.close()
        return ds.info()

    def dataset_preview(self, dataset_id: str, table: str, n: int = 10) -> dict:
        df = self.datasets[dataset_id].preview(table, n)
        return {"columns": list(df.columns), "rows": df.astype(object).where(df.notna(), None).values.tolist()}

    def _agent_for(self, dataset_id: str) -> Agent:
        if dataset_id not in self.datasets:
            raise KeyError("Unknown or expired dataset; please upload your files again.")
        if dataset_id not in self._ds_agents:
            ds = self.datasets[dataset_id]
            cfg = self.cfg.model_copy(update={"fewshot_k": 0, "pruning": False})
            self._ds_agents[dataset_id] = Agent(cfg, self.llm, con=ds.con, ctx=ds.ctx,
                                                dataset_desc=ds.description, block_pii=False)
        return self._ds_agents[dataset_id]

    def _cap_ok(self) -> bool:
        with self._lock:
            today = time.strftime("%Y-%m-%d")
            if today != self._day:
                self._day, self._count = today, 0
            self._count += 1
            return self._count <= self.daily_cap

    def ask(self, question: str, session_id: str = "default", dataset_id: str | None = None) -> dict:
        t0 = time.time()
        if dataset_id and self.mode != "live":
            return self._fail("Querying uploaded data needs an LLM: no API key is configured on this server.")
        if not self._cap_ok():
            return self._fail("Daily request cap reached; try the sample questions or come back tomorrow.")
        if self.mode == "demo":
            res = self._demo(question)
        else:
            try:
                agent = self._agent_for(dataset_id) if dataset_id else self.agent
            except KeyError as e:
                return self._fail(str(e.args[0]))
            hkey = f"{session_id}:{dataset_id or 'olist'}"
            try:
                res = agent.run(question, self.history[hkey], session_id)
            except Exception as e:  # noqa: BLE001 - provider outage / bad model name must not crash the UI
                res = AgentResult("failed", message=f"LLM call failed: {str(e)[:200]}")
            if res.status == "ok":
                self.history[hkey] = (self.history[hkey] + [
                    {"question": res.standalone_question or question, "sql": res.sql, "assumptions": res.assumptions}])[-3:]
        return self._render(res, question, time.time() - t0)

    @staticmethod
    def _fail(msg: str) -> dict:
        return {"status": "failed", "message": msg, "sql": None, "assumptions": [], "columns": [], "rows": [],
                "chart": None, "explanation": None, "attempts": [], "latency_ms": 0, "truncated": False,
                "blocked_by": None, "mode": "live"}

    def _demo(self, question: str) -> AgentResult:
        s = self.samples.get(question)
        if not s:
            return AgentResult("refused", message="Demo mode (no LLM key configured): pick one of the sample questions.")
        res = AgentResult("failed")
        try:
            sql = validate_and_rewrite(s["sql"], self.cfg.dialect, self.agent.allowed, self.cfg.max_rows, self.agent.columns)
            rows, cols = execute_readonly(self.agent.con, sql, self.cfg.timeout_s, self.cfg.max_rows)
            res.status, res.sql, res.rows, res.columns = "ok", sql, rows, cols
            res.assumptions = s.get("assumptions", []) + ["Demo mode: SQL was pre-written, not generated by a model."]
            res.attempts = [{"sql": sql, "stage": "ok"}]
        except (SQLValidationError, Exception) as e:  # noqa: BLE001
            res.message = str(e)
        return res

    def _render(self, res: AgentResult, question: str, elapsed: float) -> dict:
        chart, explanation = None, None
        if res.status == "ok":
            df = normalize_df(pd.DataFrame(res.rows, columns=res.columns))
            kind = choose_chart(df)
            fig = make_figure(df, kind)
            chart = {"kind": kind, "kinds": available_kinds(df),
                     "figure": json.loads(fig.to_json()) if fig is not None else None}
            if self.with_explanation:
                try:
                    explanation = explain(self.llm, question, res.sql, res.assumptions, res.columns, res.rows)
                except Exception:  # noqa: BLE001 - explanation is optional
                    explanation = None
        return {"status": res.status, "message": res.message, "sql": res.sql, "assumptions": res.assumptions,
                "columns": res.columns, "rows": [list(r) for r in res.rows], "truncated": res.truncated,
                "chart": chart, "explanation": explanation, "attempts": res.attempts,
                "blocked_by": res.blocked_by, "mode": self.mode, "latency_ms": int(elapsed * 1000)}


class _NoLLM:
    def complete(self, *a, **k):
        from ..llm.client import CacheMiss
        raise CacheMiss("no LLM configured")
