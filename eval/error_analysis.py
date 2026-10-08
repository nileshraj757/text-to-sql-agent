"""Aggregate error labels into ERRORS.md tables. Auto labels are heuristics; override by editing the
`error_label` column in the results CSV (valid labels in LABELS), then re-run."""
import argparse, collections, json
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
LABELS = ["test_set_error", "syntax_dialect_error", "hallucinated_schema", "wrong_join", "wrong_aggregation",
          "wrong_filter_date_logic", "business_logic_misunderstanding", "ambiguity", "evaluator_artifact"]
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("csv"); a = ap.parse_args()
    df = pd.read_csv(a.csv); bad = df[~df.correct]
    T = {json.loads(l)["id"]: json.loads(l) for l in open(ROOT / "eval/testset_v1.jsonl")}
    print(f"{len(bad)} failures of {len(df)}\n\n| Label | Count |\n|---|---|")
    for k, v in collections.Counter(bad.error_label.fillna("unlabeled")).most_common():
        print(f"| {k} | {v} |")
    print("\nWorked examples:")
    for _, r in bad.head(20).iterrows():
        t = T[r.id]
        print(f"\n### {r.id} [{r.error_label}] {t['question']}\n- gold: `{t['gold_sql']}`\n- predicted: `{r.sql}`\n- status: {r.status} {r.message if isinstance(r.message, str) else ''}")
