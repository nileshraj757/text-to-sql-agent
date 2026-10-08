"""Eval harness. One command -> results CSV + metrics JSON (+ markdown table).

  python eval/run_eval.py --config configs/step6_guardrails.yaml --split dev
  python eval/run_eval.py --config configs/best.yaml --subset smoke --llm oracle     # harness/pipeline self-test (CI)
  python eval/run_eval.py --config configs/best.yaml --cache-only                    # replay cached LLM responses

`--llm oracle` returns the GOLD SQL for answerable questions and refusals for the rest. It measures the harness,
comparator, validator false-positive rate and pipeline plumbing. It says NOTHING about model quality.
"""
from __future__ import annotations
import argparse, json, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))
import duckdb, numpy as np, pandas as pd

from eval.compare import results_match, superset_match
from t2s.agent.pipeline import Agent
from t2s.guardrails.schema_check import find_schema_hallucinations, load_columns
from t2s.llm.client import CallableLLM, make_llm
from t2s.utils.config import AgentConfig, DB_PATH

TESTSET = ROOT / "eval/testset_v1.jsonl"
RESULTS = ROOT / "eval/results"
SMOKE = None  # computed: first 2 dev questions of every tier


def load_testset(split: str, subset: str | None) -> list[dict]:
    T = [json.loads(l) for l in open(TESTSET)]
    if split != "all":
        T = [t for t in T if t["split"] == split]
    if subset == "smoke":
        seen: dict[str, int] = {}
        out = []
        for t in T:
            seen[t["tier"]] = seen.get(t["tier"], 0) + 1
            if seen[t["tier"]] <= 2:
                out.append(t)
        T = out
    return T


def oracle_llm(testset: list[dict]) -> CallableLLM:
    by_q = {t["question"]: t for t in testset}

    def fn(system, user):
        m = re.search(r"QUESTION: (.*?)(?:\n\n|$)", user, re.S)
        q = (m.group(1) if m else user).strip()
        t = by_q.get(q)
        if t is None:
            return json.dumps({"sql": None, "assumptions": [], "clarification": None, "refuse_reason": "unknown"})
        if t.get("ambiguous"):
            return json.dumps({"sql": None, "assumptions": [], "clarification": "Which metric do you mean?", "refuse_reason": None})
        if not t["answerable"]:
            return json.dumps({"sql": None, "assumptions": [], "clarification": None, "refuse_reason": "oracle refusal"})
        return json.dumps({"sql": t["gold_sql"], "assumptions": ["oracle"], "clarification": None, "refuse_reason": None})
    return CallableLLM(fn)


def classify_failure(t, res, hallucinated, gold_df, pred_df) -> str:
    """Heuristic first-pass label; a human confirms/overrides in ERRORS.md (see docs/error_taxonomy)."""
    if res.status != "ok":
        if t["answerable"]:
            if res.status in ("refused", "clarify"):
                return "over_refusal"
            if res.status == "blocked":
                return "validator_false_positive" if res.blocked_by == "validator" else "input_guard_false_positive"
            return "syntax_or_hallucination" if res.attempts and any(a.get("stage") in ("validate", "execute", "parse") for a in res.attempts) else "failed_other"
        return "should_have_refused"
    if hallucinated:
        return "hallucinated_schema"
    if gold_df is not None and pred_df is not None:
        if superset_match(gold_df, pred_df, t["ordered"]):
            return "evaluator_artifact_extra_columns"
        if gold_df.shape[0] != pred_df.shape[0]:
            return "wrong_filter_join_or_aggregation"  # needs human label (join/aggregation/filter/business logic)
    return "unlabeled"


def score(t: dict, res, gold_df, pred_df) -> tuple[bool, str]:
    """Returns (correct, kind). kind: exec | refusal | ambiguity."""
    if t.get("ambiguous"):
        return (res.status == "clarify") or (res.status == "ok" and len(res.assumptions) > 0), "ambiguity"
    if t["answerable"]:
        return (res.status == "ok" and pred_df is not None and results_match(gold_df, pred_df, ordered=t["ordered"])), "exec"
    return res.status in ("refused", "clarify", "blocked"), "refusal"


def run(cfg: AgentConfig, testset: list[dict], llm, label: str) -> pd.DataFrame:
    con_gold = duckdb.connect(str(DB_PATH), read_only=True)
    agent = Agent(cfg, llm)
    cols = load_columns(agent.con)
    rows = []
    for i, t in enumerate(testset):
        gold_df = con_gold.execute(t["gold_sql"]).fetch_df() if t["gold_sql"] else None
        res = agent.run(t["question"], [], session_id=f"eval-{label}")
        pred_df = pd.DataFrame(res.rows, columns=res.columns) if res.status == "ok" else None
        correct, kind = score(t, res, gold_df if t["answerable"] else None, pred_df)
        first_sql = res.raw_sqls[0] if res.raw_sqls else None
        hallucinated = bool(first_sql and find_schema_hallucinations(first_sql, cols))
        first_failed = bool(res.attempts) and res.attempts[0].get("stage") != "ok"
        executed_ok = any(a.get("stage") == "ok" for a in res.attempts)
        cost = (res.prompt_tokens * cfg.price_in_per_mtok + res.completion_tokens * cfg.price_out_per_mtok) / 1e6
        rows.append({
            "id": t["id"], "tier": t["tier"], "split": t["split"], "kind": kind, "status": res.status, "correct": correct,
            "executed_ok": executed_ok, "generated_sql": bool(res.raw_sqls), "hallucinated_schema": hallucinated,
            "first_attempt_failed": first_failed, "recovered": first_failed and executed_ok,
            "n_attempts": len(res.attempts), "latency_s": round(res.latency_s, 3), "prompt_tokens": res.prompt_tokens,
            "completion_tokens": res.completion_tokens, "cost_usd": cost, "blocked_by": res.blocked_by or "",
            "sql": res.sql or first_sql or "", "message": res.message,
            "error_label": "" if correct else classify_failure(t, res, hallucinated, gold_df, pred_df),
        })
        print(f"[{i+1}/{len(testset)}] {t['id']} {t['tier']:13s} {res.status:8s} {'OK ' if correct else 'BAD'}", flush=True)
    return pd.DataFrame(rows)


def aggregate(df: pd.DataFrame) -> dict:
    ex = df[df.kind == "exec"]
    ref = df[df.kind == "refusal"]
    amb = df[df.kind == "ambiguity"]
    gen = df[df.generated_sql]
    # refusal accuracy: correct refusal on unanswerable/unsafe AND correct non-refusal on answerable
    non_ref_ok = (~ex.status.isin(["refused", "clarify", "blocked"])).mean() if len(ex) else np.nan
    m = {
        "n": int(len(df)),
        "execution_accuracy": float(ex.correct.mean()) if len(ex) else None,
        "valid_sql_rate": float(gen.executed_ok.mean()) if len(gen) else None,
        "schema_hallucination_rate": float(gen.hallucinated_schema.mean()) if len(gen) else None,
        "refusal_accuracy": float(ref.correct.mean()) if len(ref) else None,
        "non_refusal_rate_on_answerable": float(non_ref_ok) if len(ex) else None,
        "ambiguity_handled": float(amb.correct.mean()) if len(amb) else None,
        "overall_accuracy": float(df.correct.mean()),
        "self_correction_success": float(df[df.first_attempt_failed].recovered.mean()) if df.first_attempt_failed.any() else None,
        "latency_p50_s": float(df.latency_s.median()), "latency_p95_s": float(df.latency_s.quantile(0.95)),
        "tokens_per_query": float((df.prompt_tokens + df.completion_tokens).mean()),
        "cost_per_query_usd": float(df.cost_usd.mean()),
        "by_tier": {k: float(v) for k, v in df.groupby("tier").correct.mean().items()},
        "false_positive_blocks_on_answerable": int(((df.kind == "exec") & (df.status == "blocked")).sum()),
    }
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    ap.add_argument("--subset", default=None, choices=[None, "smoke"])
    ap.add_argument("--llm", default="real", choices=["real", "oracle"])
    ap.add_argument("--cache-only", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--fallback", default=None, help="provider:model")
    ap.add_argument("--out", default=None, help="metrics JSON path")
    a = ap.parse_args()

    cfg = AgentConfig.load(a.config)
    testset = load_testset(a.split, a.subset)
    if a.split == "test":
        print("NOTE: the test split must be run ONCE at the end. Log this run in docs/devlog.md.")
    if a.llm == "oracle":
        llm, label = oracle_llm(json.load(open(ROOT / "eval/testset_v1.jsonl")) if False else [json.loads(l) for l in open(TESTSET)]), f"ORACLE-{cfg.name}"
    else:
        llm, label = make_llm(cfg, cache=not a.no_cache, cache_only=a.cache_only, fallback=a.fallback), cfg.name
    df = run(cfg, testset, llm, label)
    metrics = {"config": cfg.model_dump(), "llm": a.llm, "split": a.split, "subset": a.subset, **aggregate(df)}
    RESULTS.mkdir(parents=True, exist_ok=True)
    stem = f"{'oracle_' if a.llm == 'oracle' else ''}{cfg.name}_{a.split}{'_smoke' if a.subset else ''}"
    df.to_csv(RESULTS / f"{stem}.csv", index=False)
    out = Path(a.out) if a.out else RESULTS / f"{stem}.json"
    out.write_text(json.dumps(metrics, indent=2))
    print(json.dumps({k: v for k, v in metrics.items() if k not in ("config", "by_tier")}, indent=2))
    print("by tier:", json.dumps(metrics["by_tier"]))


if __name__ == "__main__":
    main()
