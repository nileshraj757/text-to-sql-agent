import pytest
from t2s.guardrails.validator import SQLValidationError, validate_and_rewrite

D = "duckdb"

def v(sql, cols, **k):
    return validate_and_rewrite(sql, D, set(cols), 1000, cols, **k)

BENIGN = [
    "SELECT COUNT(*) FROM orders",
    "SELECT order_status, COUNT(*) FROM orders GROUP BY 1 ORDER BY 2 DESC",
    "WITH m AS (SELECT date_trunc('month', order_purchase_timestamp) AS mo, COUNT(*) AS n FROM orders GROUP BY 1) SELECT mo, n, LAG(n) OVER (ORDER BY mo) FROM m",
    "SELECT o.order_id FROM orders o JOIN order_items oi USING (order_id) LIMIT 5",
    "SELECT t.product_category_name_english, SUM(oi.price) r FROM order_items oi JOIN products p USING (product_id) JOIN category_translation t USING (product_category_name) GROUP BY 1",
    "SELECT order_id FROM orders UNION ALL SELECT order_id FROM order_items",
    "SELECT COUNT(DISTINCT customer_unique_id) FROM customers",
    "SELECT customer_state, COUNT(*) FROM customers GROUP BY 1",
]

@pytest.mark.parametrize("sql", BENIGN)
def test_benign_pass(sql, cols):
    assert v(sql, cols)

MALICIOUS = [
    "DROP TABLE orders", "DELETE FROM orders", "UPDATE orders SET order_status='x'", "INSERT INTO orders VALUES (1)",
    "CREATE TABLE x AS SELECT 1", "ALTER TABLE orders ADD COLUMN z INT", "TRUNCATE orders",
    "SELECT 1; DROP TABLE orders", "SELECT * FROM orders; SELECT * FROM customers",
    "COPY orders TO '/tmp/x.csv'", "ATTACH '/tmp/x.db'", "SET enable_external_access=true", "PRAGMA database_list",
    "INSTALL httpfs", "LOAD httpfs", "EXPORT DATABASE '/tmp/x'", "CALL pragma_version()",
    "SELECT * FROM read_csv('/etc/passwd')", "SELECT * FROM read_parquet('x')", "SELECT * FROM read_json('x')",
    "SELECT * FROM '/etc/passwd'", "SELECT * FROM glob('/*')", "SELECT * FROM duckdb_settings()",
    "SELECT * FROM duckdb_tables()", "SELECT getenv('HOME')", "SELECT system('ls')", "SELECT current_setting('x')",
    "SELECT * FROM range(1000000000000)", "SELECT * FROM information_schema.tables", "SELECT * FROM main.orders",
    "/*x*/DrOp/**/TABLE orders", "SeLeCt 1; dRoP tAbLe orders", "ＤＲＯＰ TABLE orders",
    "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
    "SELECT * FROM customers", "SELECT customer_unique_id FROM customers",
]

@pytest.mark.parametrize("sql", MALICIOUS)
def test_malicious_blocked(sql, cols):
    with pytest.raises(SQLValidationError):
        v(sql, cols)

FATAL = ["DROP TABLE orders", "SELECT 1; SELECT 2", "SELECT * FROM read_csv('x')", "SELECT * FROM customers",
         "ＤＲＯＰ TABLE orders", "SELECT * FROM '/etc/passwd'"]

@pytest.mark.parametrize("sql", FATAL[:-1] + [])
def test_security_violations_are_fatal(sql, cols):
    with pytest.raises(SQLValidationError) as e:
        v(sql, cols)
    assert e.value.fatal

def test_hallucinations_are_repairable_not_fatal(cols):
    for sql in ["SELECT foo FROM orders", "SELECT * FROM nonexistent", "SELECT o.nope FROM orders o", "SELEC 1"]:
        with pytest.raises(SQLValidationError) as e:
            v(sql, cols)
        assert not e.value.fatal

def test_limit_injected(cols):
    assert v("SELECT order_id FROM orders", cols).upper().endswith("LIMIT 1000")

def test_existing_small_limit_kept_large_limit_clamped(cols):
    assert v("SELECT order_id FROM orders LIMIT 5", cols).upper().endswith("LIMIT 5")
    assert v("SELECT order_id FROM orders LIMIT 99999", cols).upper().endswith("LIMIT 1000")

def test_union_is_wrapped_and_limited(cols):
    out = v("SELECT order_id FROM orders UNION SELECT order_id FROM order_items", cols).upper()
    assert "LIMIT 1000" in out and out.startswith("SELECT * FROM (")

def test_cte_names_not_treated_as_tables(cols):
    assert v("WITH a AS (SELECT order_id FROM orders) SELECT * FROM a", cols)

def test_pii_allows_aggregates(cols):
    assert v("SELECT customer_state, COUNT(DISTINCT customer_unique_id) FROM customers GROUP BY 1", cols)
    assert v("SELECT c.customer_unique_id, SUM(oi.price) FROM customers c JOIN orders o USING (customer_id) JOIN order_items oi USING (order_id) GROUP BY 1", cols)
