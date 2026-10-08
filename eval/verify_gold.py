"""Independent verification of gold SQL: (1) pandas recomputation of key questions, (2) top-N tie detection,
(3) few-shot/eval leakage via embedding similarity. Exit 1 on any failure."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))
import duckdb, numpy as np, pandas as pd
from t2s.agent.embed import HashingEmbedder
from t2s.utils.config import DB_PATH
from eval.compare import results_match

RAW = ROOT / "data/raw"
con = duckdb.connect(str(DB_PATH), read_only=True)
T = [json.loads(l) for l in open(ROOT / "eval/testset_v1.jsonl")]
byq = {t["question"]: t for t in T}
gold = lambda q: con.execute(byq[q]["gold_sql"]).fetch_df()  # noqa: E731
rd = lambda n, **k: pd.read_csv(RAW / f"{n}.csv", **k)  # noqa: E731
orders, items = rd("olist_orders_dataset", parse_dates=["order_purchase_timestamp", "order_delivered_customer_date", "order_estimated_delivery_date"]), rd("olist_order_items_dataset")
cust, rev, pay = rd("olist_customers_dataset"), rd("olist_order_reviews_dataset"), rd("olist_order_payments_dataset")
prod, trans, sell = rd("olist_products_dataset"), rd("product_category_name_translation"), rd("olist_sellers_dataset")
fails = []

def check(q, expected_df):
    ok = results_match(gold(q), expected_df, ordered=byq[q]["ordered"])
    print(("PASS " if ok else "FAIL ") + q[:80])
    if not ok:
        fails.append(q)

valid = orders[~orders.order_status.isin(["canceled", "unavailable"])]
check("How many orders were canceled?", pd.DataFrame([[int((orders.order_status == "canceled").sum())]]))
check("What is the average review score, rounded to 2 decimals?", pd.DataFrame([[rev.review_score.mean()]]))
check("How many real customers (unique people) placed more than one order?",
      pd.DataFrame([[int((orders.merge(cust, on="customer_id").groupby("customer_unique_id").order_id.nunique() > 1).sum())]]))
vi = items.merge(valid, on="order_id").merge(prod, on="product_id").merge(trans, on="product_category_name")
top = vi.groupby("product_category_name_english").price.sum().reset_index().sort_values(["price", "product_category_name_english"], ascending=[False, True]).head(10)
check("What are the top 10 English product categories by revenue, excluding canceled and unavailable orders?", top)
vs = items.merge(valid, on="order_id").merge(cust, on="customer_id").groupby("customer_state").price.sum().reset_index()
check("What is the revenue by customer state, excluding canceled and unavailable orders?", vs)
d = orders.merge(cust, on="customer_id").dropna(subset=["order_delivered_customer_date"])
d["days"] = (d.order_delivered_customer_date.dt.normalize() - d.order_purchase_timestamp.dt.normalize()).dt.days
check("What is the average delivery time in days (purchase to delivery to the customer) by customer state, rounded to 1 decimal? Only count orders that were delivered.",
      d.groupby("customer_state").days.mean().round(1).reset_index())
check("How many orders were delivered after the estimated delivery date?",
      pd.DataFrame([[int((orders.order_delivered_customer_date > orders.order_estimated_delivery_date).sum())]]))
check("How many orders were paid with more than one payment type?", pd.DataFrame([[int((pay.groupby("order_id").payment_type.nunique() > 1).sum())]]))
check("How many products have never been sold?", pd.DataFrame([[int((~prod.product_id.isin(items.product_id)).sum())]]))
check("What is the total payment value of delivered orders, rounded to 2 decimals?",
      pd.DataFrame([[pay.merge(orders[orders.order_status == "delivered"], on="order_id").payment_value.sum()]]))
sc = items.merge(rev, on="order_id").groupby("seller_id").review_score.mean()
check("How many sellers have an average review score below the overall average review score?", pd.DataFrame([[int((sc < rev.review_score.mean()).sum())]]))

# tie detection on gold with LIMIT: the value just beyond the cut must differ from the last kept value
import sqlglot
for t in T:
    if not t["gold_sql"]:
        continue
    tree = sqlglot.parse_one(t["gold_sql"], read="duckdb")
    lim = tree.args.get("limit")
    if lim is None or not t["ordered"]:
        continue
    n = int(lim.expression.this)
    full = con.execute(sqlglot.parse_one(t["gold_sql"], read="duckdb").copy().set("limit", None) or t["gold_sql"]).fetch_df() \
        if False else con.execute(tree.copy().limit(n + 1).sql("duckdb")).fetch_df()
    if len(full) > n and n > 0:
        valcol = [c for c in full.columns if full[c].dtype.kind in "if"]
        if valcol and full[valcol[-1]].iloc[n - 1] == full[valcol[-1]].iloc[n]:
            print(f"TIE   {t['id']} {t['question'][:70]} (tiebreaker present in gold: ", "yes" if ", " in t["gold_sql"].split("ORDER BY")[-1] else "NO", ")")

# leakage: few-shot vs eval question similarity
pool = [json.loads(l) for l in open(ROOT / "prompts/fewshot_pool.jsonl")]
emb = HashingEmbedder()
S = emb.encode([p["question"] for p in pool]) @ emb.encode([t["question"] for t in T]).T
mx = S.max()
i, j = np.unravel_index(S.argmax(), S.shape)
print(f"max few-shot/eval similarity {mx:.2f}: '{pool[i]['question']}' ~ '{T[j]['question']}'")
if mx > 0.8:
    fails.append("fewshot leakage")
sys.exit(1 if fails else 0)
