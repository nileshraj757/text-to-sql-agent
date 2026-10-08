import pytest
from t2s.guardrails.executor import ExecutionError, execute_readonly, explain_has_cross_product

def test_basic_and_row_cap(con):
    rows, cols = execute_readonly(con, "SELECT * FROM order_items", 10, 7)
    assert len(rows) == 7 and "price" in cols

@pytest.mark.parametrize("sql", ["DROP TABLE orders", "DELETE FROM orders", "CREATE TABLE z(a int)",
                                 "SELECT * FROM read_csv('/etc/passwd')", "SET enable_external_access=true",
                                 "ATTACH '/tmp/z.db'", "COPY orders TO '/tmp/z.csv'"])
def test_database_layer_blocks_even_without_validator(con, sql):
    with pytest.raises(ExecutionError):
        execute_readonly(con, sql, 5, 10)

def test_timeout_interrupts_runaway_query(con):
    with pytest.raises(ExecutionError) as e:
        execute_readonly(con, "SELECT COUNT(*) FROM geolocation a, geolocation b, geolocation c", 1, 10)
    assert e.value.timeout
    assert execute_readonly(con, "SELECT 1", 5, 10)[0] == [(1,)]   # connection still healthy afterwards

def test_cross_product_detected(con):
    assert explain_has_cross_product(con, "SELECT * FROM orders CROSS JOIN order_items")
    assert not explain_has_cross_product(con, "SELECT * FROM orders JOIN order_items USING (order_id)")
