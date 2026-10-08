"""Run the experiment ladder (steps 1-6, 6b) on a split and write eval/results/ladder.md + ladder.json.
Every cell comes from a metrics JSON a script produced. Missing runs stay blank."""
import argparse, json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "eval/results"
STEPS = [("1", "Zero-shot, raw DDL only", "step1_zeroshot_ddl"), ("2", "+ descriptions, enum values, glossary", "step2_descriptions"),
         ("3", "+ retrieved few-shot", "step3_fewshot"), ("4", "+ schema pruning/linking", "step4_pruning"),
         ("5", "+ self-correction (max 2 retries)", "step5_selfcorrect"), ("6", "+ guardrails (final system)", "step6_guardrails"),
         ("6b", "Final system, small open model", "step6b_small_model")]
TIERS = ["single_table", "aggregation", "join", "multi_join", "subquery_cte", "window", "date_logic"]


def f(x, pct=False, nd=3):
    if x is None:
        return ""
    return f"{100*x:.1f}%" if pct else f"{x:.{nd}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    ap.add_argument("--run", action="store_true", help="execute the evals (needs an LLM) instead of just tabulating")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    out = {}
    for sid, desc, name in STEPS:
        if a.only and sid not in a.only:
            continue
        p = RES / f"{name}_{a.split}.json"
        if a.run:
            subprocess.run([sys.executable, str(ROOT / "eval/run_eval.py"), "--config", str(ROOT / f"configs/{name}.yaml"), "--split", a.split], check=False)
        if p.exists():
            out[sid] = json.loads(p.read_text())
    L = ["| # | Configuration | Exec acc. | Valid-SQL | Halluc. schema % | Refusal acc. | p50 latency (s) | Tokens/query | $/query |", "|---|---|---|---|---|---|---|---|---|"]
    L.append("| 0 | External baseline (Vanna), default settings | | | | | | | |")
    for sid, desc, name in STEPS:
        m = out.get(sid)
        L.append(f"| {sid} | {desc} | " + (" | ".join([f(m["execution_accuracy"], 1), f(m["valid_sql_rate"], 1), f(m["schema_hallucination_rate"], 1),
                 f(m["refusal_accuracy"], 1), f(m["latency_p50_s"], nd=2), f(m["tokens_per_query"], nd=0), f(m["cost_per_query_usd"], nd=5)]) if m else " | ".join([""] * 7)) + " |")
    L += ["", "| Tier | " + " | ".join(f"Step {s}" for s in ["1", "2", "3", "5", "6"]) + " |", "|---|---|---|---|---|---|"]
    for t in TIERS:
        L.append(f"| {t} | " + " | ".join(f(out[s]["by_tier"].get(t), 1) if s in out else "" for s in ["1", "2", "3", "5", "6"]) + " |")
    (RES / "ladder.md").write_text("\n".join(L) + "\n")
    (RES / "ladder.json").write_text(json.dumps(out, indent=1))
    print("\n".join(L))


if __name__ == "__main__":
    main()
