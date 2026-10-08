"""Load Olist CSVs into DuckDB with clean table names."""
import sys
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW, DB = ROOT / "data/raw", ROOT / "data/db/olist.duckdb"
TABLES = {
    "customers": "olist_customers_dataset",
    "geolocation": "olist_geolocation_dataset",
    "order_items": "olist_order_items_dataset",
    "order_payments": "olist_order_payments_dataset",
    "order_reviews": "olist_order_reviews_dataset",
    "orders": "olist_orders_dataset",
    "products": "olist_products_dataset",
    "sellers": "olist_sellers_dataset",
    "category_translation": "product_category_name_translation",
}

def main():
    DB.parent.mkdir(parents=True, exist_ok=True)
    DB.unlink(missing_ok=True)
    con = duckdb.connect(str(DB))
    for t, f in TABLES.items():
        p = RAW / f"{f}.csv"
        if not p.exists():
            sys.exit(f"missing {p}; run scripts/download_data.sh")
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_csv_auto('{p}', header=true, sample_size=-1)")
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t:22s}{n:>10,}")
    con.close()

if __name__ == "__main__":
    main()
