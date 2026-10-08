"""Step 0: external baseline with Vanna (default settings). UNTESTED here (no LLM key in the build environment).
  pip install vanna chromadb openai ; set GROQ_API_KEY ; python eval/baselines/vanna_baseline.py --split dev
Vanna's API has changed across versions; this targets the 0.x local-vector-store classes. Adapt if yours differs.
It writes eval/results/vanna_<split>.csv in the same format so aggregate() can score it."""
import argparse, json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))
import duckdb, pandas as pd
from eval.compare import results_match
from t2s.utils.config import DB_PATH

def main():
    from openai import OpenAI
    from vanna.chromadb import ChromaDB_VectorStore
    from vanna.openai import OpenAI_Chat

    class V(ChromaDB_VectorStore, OpenAI_Chat):
        def __init__(self, cfg):
            ChromaDB_VectorStore.__init__(self, config=cfg)
            OpenAI_Chat.__init__(self, client=OpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ_API_KEY"]), config=cfg)

    ap = argparse.ArgumentParser(); ap.add_argument("--split", default="dev"); a = ap.parse_args()
    vn = V({"model": "openai/gpt-oss-120b"})
    con = duckdb.connect(str(DB_PATH), read_only=True)
    for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall():   # DDL only = "default settings"
        ddl = "CREATE TABLE %s (%s)" % (t, ", ".join(f"{c} {d}" for c, d in con.execute("SELECT column_name,data_type FROM information_schema.columns WHERE table_name=?", [t]).fetchall()))
        vn.train(ddl=ddl)
    rows = []
    for l in open(ROOT / "eval/testset_v1.jsonl"):
        t = json.loads(l)
        if t["split"] != a.split or not t["answerable"]:
            continue
        try:
            sql = vn.generate_sql(t["question"]); pred = con.execute(sql).fetch_df(); ok = results_match(con.execute(t["gold_sql"]).fetch_df(), pred, t["ordered"])
        except Exception as e:  # noqa: BLE001
            sql, ok = str(e), False
        rows.append({"id": t["id"], "tier": t["tier"], "correct": ok, "sql": sql})
    df = pd.DataFrame(rows); df.to_csv(ROOT / f"eval/results/vanna_{a.split}.csv", index=False)
    print("execution accuracy on answerable:", df.correct.mean())

if __name__ == "__main__":
    main()
