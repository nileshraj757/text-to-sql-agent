"""Core loop: input guard -> link -> generate -> validate -> execute -> repair. Plain Python state machine."""
from __future__ import annotations
import json, re, time, uuid
from dataclasses import dataclass, field

from ..guardrails.executor import ExecutionError, execute_readonly, explain_has_cross_product, make_connection
from ..guardrails.input_guard import check_input
from ..guardrails.schema_check import find_schema_hallucinations, load_columns
from ..guardrails.validator import SQLValidationError, validate_and_rewrite
from ..llm.client import LLM, CacheMiss
from ..utils.config import AgentConfig, DB_PATH
from ..utils.logging import audit_event
from .fewshot import FewShot
from .linking import SchemaLinker
from .prompts import REWRITE_SYSTEM, build_user_prompt, system_prompt
from .schema_context import SchemaContext


@dataclass
class AgentResult:
    status: str                                   # ok | refused | clarify | blocked | failed
    sql: str | None = None
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    assumptions: list = field(default_factory=list)
    attempts: list = field(default_factory=list)  # every try: sql, stage, error
    message: str = ""
    truncated: bool = False
    blocked_by: str | None = None                 # input_guard | validator | plan_check | database
    tables: list = field(default_factory=list)    # tables shown to the model (after pruning)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    n_llm_calls: int = 0
    latency_s: float = 0.0
    stage_latency: dict = field(default_factory=dict)
    raw_sqls: list = field(default_factory=list)  # SQL as emitted by the model, before rewriting
    standalone_question: str | None = None


def parse_model_json(text: str) -> dict:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1)
    if not t.startswith("{"):                       # tolerate chatter around the object
        a, b = t.find("{"), t.rfind("}")
        if a != -1 and b > a:
            t = t[a:b + 1]
    out = json.loads(t)
    if not isinstance(out, dict):
        raise json.JSONDecodeError("not an object", t, 0)
    return out


class Agent:
    def __init__(self, cfg: AgentConfig, llm: LLM, db_path=DB_PATH, con=None, fewshot: FewShot | None = None,
                 ctx: SchemaContext | None = None, dataset_desc: str | None = None, block_pii: bool = True):
        """Default = the Olist database. For user-uploaded data pass `con`, `ctx`, `dataset_desc` (no Olist
        few-shot pool, glossary or PII rule apply)."""
        self.cfg, self.llm = cfg, llm
        self.con = con or make_connection(db_path)
        custom = ctx is not None
        self.ctx = ctx or SchemaContext(self.con)
        self.columns = load_columns(self.con)
        self.allowed = set(self.columns)
        self.system = system_prompt(dataset_desc)
        self.block_pii = block_pii
        self.linker = SchemaLinker(self.ctx.meta) if cfg.pruning and not custom else None
        self.fewshot = fewshot if fewshot is not None else (
            FewShot() if cfg.fewshot_k > 0 and not custom else None)

    # -- helpers -------------------------------------------------------------------------------
    def _call(self, res: AgentResult, system: str, user: str):
        t0 = time.time()
        r = self.llm.complete(system, user, json_mode=True)
        res.prompt_tokens += r.prompt_tokens
        res.completion_tokens += r.completion_tokens
        res.n_llm_calls += 1
        res.stage_latency["llm"] = res.stage_latency.get("llm", 0) + (time.time() - t0)
        return r

    def rewrite_followup(self, question: str, history: list[dict], res: AgentResult) -> str:
        user = "PREVIOUS TURNS:\n" + "\n".join(f"- Q: {t['question']}\n  SQL: {t['sql']}" for t in history) + \
               f"\n\nFOLLOW-UP: {question}"
        try:
            return parse_model_json(self._call(res, REWRITE_SYSTEM, user).text).get("question") or question
        except (json.JSONDecodeError, KeyError):
            return question

    # -- main ----------------------------------------------------------------------------------
    def run(self, question: str, history: list[dict] | None = None, session_id: str | None = None) -> AgentResult:
        t_start = time.time()
        res = self._run(question, (history or [])[-self.cfg.history_turns:])
        res.latency_s = time.time() - t_start
        audit_event({"session": session_id or uuid.uuid4().hex[:8], "question": question[:500], "sql": res.sql,
                     "status": res.status, "blocked_by": res.blocked_by, "rows": len(res.rows),
                     "attempts": len(res.attempts), "latency_ms": int(res.latency_s * 1000)})
        return res

    def _run(self, question: str, history: list[dict]) -> AgentResult:
        cfg = self.cfg
        res = AgentResult("failed")
        if cfg.guardrails:
            ok, why = check_input(question, cfg.max_question_chars)
            if not ok:
                res.status, res.message, res.blocked_by = "blocked", why, "input_guard"
                return res
        if history:
            question = res.standalone_question = self.rewrite_followup(question, history, res)

        tables = self.linker.link(question) if self.linker else self.ctx.tables
        res.tables = tables
        schema_ctx = self.ctx.build(tables, cfg.descriptions, cfg.samples, cfg.glossary)
        shots = self.fewshot.select(question, cfg.fewshot_k, cfg.fewshot_mode) if self.fewshot else []

        last_sql = last_err = None
        for _ in range(cfg.max_retries + 1):
            user = build_user_prompt(question, schema_ctx, shots, history if not res.standalone_question else None,
                                     last_sql, last_err)
            try:
                resp = self._call(res, self.system, user)
            except CacheMiss as e:
                res.status, res.message = "failed", f"LLM unavailable: {e}"
                return res
            try:
                out = parse_model_json(resp.text)
            except json.JSONDecodeError:
                last_sql, last_err = None, "Output was not valid JSON. Return only the JSON object."
                res.attempts.append({"stage": "parse", "error": last_err})
                continue
            if out.get("refuse_reason"):
                res.status, res.message = "refused", str(out["refuse_reason"])
                res.assumptions = out.get("assumptions") or []
                return res
            if out.get("clarification"):
                res.status, res.message = "clarify", str(out["clarification"])
                return res
            raw_sql = out.get("sql") or ""
            res.raw_sqls.append(raw_sql)
            res.assumptions = out.get("assumptions") or []
            try:
                t0 = time.time()
                if cfg.guardrails:
                    safe_sql = validate_and_rewrite(raw_sql, cfg.dialect, self.allowed, cfg.max_rows, self.columns, self.block_pii)
                    res.stage_latency["validate"] = res.stage_latency.get("validate", 0) + time.time() - t0
                    if explain_has_cross_product(self.con, safe_sql):
                        raise SQLValidationError("Query plan contains a cartesian (CROSS) product; add join conditions.",
                                                 rule="plan_check")
                else:
                    safe_sql = raw_sql
                t0 = time.time()
                rows, cols = execute_readonly(self.con, safe_sql, cfg.timeout_s, cfg.max_rows)
                res.stage_latency["execute"] = res.stage_latency.get("execute", 0) + time.time() - t0
                res.attempts.append({"sql": safe_sql, "stage": "ok"})
                res.status, res.sql, res.columns, res.rows = "ok", safe_sql, cols, rows
                res.truncated = len(rows) >= cfg.max_rows
                return res
            except SQLValidationError as e:
                res.attempts.append({"sql": raw_sql, "stage": "validate", "error": str(e), "fatal": e.fatal, "rule": e.rule})
                if e.fatal:                                   # never let the LLM "repair" a security violation
                    res.status, res.message, res.blocked_by = "blocked", "That request isn't allowed.", "validator"
                    res.sql = raw_sql
                    audit_event({"event": "blocked", "question": question[:500], "sql": raw_sql, "reason": str(e), "rule": e.rule})
                    return res
                last_sql, last_err = raw_sql, f"Validation failed: {e}"
            except ExecutionError as e:
                res.attempts.append({"sql": raw_sql, "stage": "execute", "error": str(e), "timeout": e.timeout})
                last_sql, last_err = raw_sql, f"Database error: {e}"
        res.status, res.message = "failed", "Could not produce a valid query."
        res.sql = last_sql
        return res
