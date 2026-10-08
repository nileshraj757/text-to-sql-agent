"""Layers 2 and 3: read-only DB connection, no external access, timeout, row cap, plan check."""
from __future__ import annotations
import threading
import duckdb


class ExecutionError(Exception):
    def __init__(self, msg, timeout=False):
        super().__init__(msg)
        self.timeout = timeout


def make_connection(path: str):
    con = duckdb.connect(str(path), read_only=True)
    try:
        con.execute("SET enable_external_access=false")   # no file/network access from SQL
        con.execute("SET lock_configuration=true")        # SQL cannot flip the settings back
    except duckdb.InvalidInputException:
        pass   # DuckDB shares one instance per file in a process; it was already configured and locked
    return con


def explain_has_cross_product(con, sql: str) -> bool:
    plan = "\n".join(str(r[1]) for r in con.cursor().execute("EXPLAIN " + sql).fetchall())
    return "CROSS_PRODUCT" in plan


def execute_readonly(con, sql: str, timeout_s: float = 10, max_rows: int = 1000):
    """Run on a per-request cursor so an interrupt never affects other sessions."""
    cur = con.cursor()
    timer = threading.Timer(timeout_s, cur.interrupt)
    timed_out = threading.Event()
    timer.start()
    try:
        try:
            cur.execute(sql)
            rows = cur.fetchmany(max_rows)
            cols = [d[0] for d in cur.description]
            return rows, cols
        except Exception as e:  # noqa: BLE001
            if "INTERRUPT" in str(e).upper():
                timed_out.set()
                raise ExecutionError(f"Query exceeded {timeout_s}s timeout", timeout=True)
            raise ExecutionError(str(e).splitlines()[0] if str(e) else repr(e))
    finally:
        timer.cancel()
        cur.close()
