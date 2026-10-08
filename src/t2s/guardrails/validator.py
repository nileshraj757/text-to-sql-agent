"""Layer 1: deterministic AST validator. The prompt is a request; this is a guarantee."""
from __future__ import annotations
import re
import unicodedata
import sqlglot
from sqlglot import exp

FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command,
                   exp.Merge, exp.Copy, exp.Pragma, exp.Set, exp.Use, exp.Attach, exp.Detach,
                   exp.Install, exp.Export, exp.TruncateTable, exp.Transaction, exp.Commit, exp.Rollback)
BLOCKED_FUNCS = {"read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto", "read_text",
                 "read_blob", "glob", "pg_sleep", "pg_read_file", "lo_import", "load_extension",
                 "system", "getenv", "current_setting", "sniff_csv", "query", "query_table", "which_secret"}
BLOCKED_PREFIXES = ("duckdb_", "pragma_", "read_", "parquet_", "iceberg_", "delta_", "sqlite_", "postgres_")
DANGEROUS_LEADERS = {"drop", "delete", "update", "insert", "create", "alter", "truncate", "copy", "attach",
                     "detach", "pragma", "set", "install", "load", "export", "import", "call", "grant",
                     "revoke", "vacuum", "checkpoint", "begin", "commit", "rollback", "merge", "replace"}
AGG_NODES = (exp.AggFunc,)
# customer-level identifiers: listing them row-by-row is PII exfiltration (aggregates are fine)
PII_COLUMNS = {"customer_unique_id", "customer_zip_code_prefix", "customer_city"}
PII_TABLES = {"customers"}


class SQLValidationError(Exception):
    def __init__(self, msg, fatal=False, rule="syntax"):
        super().__init__(msg)
        self.fatal = fatal          # fatal = security violation: block, never ask the LLM to "fix" it
        self.rule = rule


def _first_word(sql: str) -> str:
    sql = unicodedata.normalize("NFKC", sql)          # fullwidth / lookalike letters -> ASCII for leader detection
    s = re.sub(r"(--[^\n]*\n|/\*.*?\*/)", " ", sql, flags=re.S).strip().lstrip("(").strip()
    m = re.match(r"[A-Za-z_]+", s)
    return m.group(0).lower() if m else ""


def _func_name(f: exp.Func) -> str:
    if isinstance(f, exp.Anonymous):
        return f.name.lower()
    return type(f).sql_names()[0].lower() if f.sql_names() else type(f).__name__.lower()


def validate_and_rewrite(sql: str, dialect: str, allowed_tables: set[str], max_rows: int = 1000,
                         columns: dict[str, set[str]] | None = None, block_pii: bool = True) -> str:
    """Return the safe, LIMIT-bounded SQL, or raise SQLValidationError (fatal => security block)."""
    if not sql or not sql.strip():
        raise SQLValidationError("Empty SQL", rule="empty")
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except sqlglot.errors.SqlglotError as e:
        if _first_word(sql) in DANGEROUS_LEADERS:
            raise SQLValidationError(f"Non-SELECT statement ({_first_word(sql)})", fatal=True, rule="statement_type")
        raise SQLValidationError(f"Syntax error: {e}", rule="syntax")
    if len(statements) != 1:
        raise SQLValidationError("Exactly one statement allowed", fatal=True, rule="multi_statement")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union)):
        raise SQLValidationError("Only SELECT queries are allowed", fatal=True, rule="statement_type")
    if tree.find(*FORBIDDEN_NODES):
        raise SQLValidationError("Data-modifying, DDL or session statement detected", fatal=True, rule="forbidden_node")

    for f in tree.find_all(exp.Func):
        name = _func_name(f)
        if name in BLOCKED_FUNCS or name.startswith(BLOCKED_PREFIXES) or isinstance(f, exp.ReadCSV):
            raise SQLValidationError(f"Function not allowed: {name}", fatal=True, rule="blocked_function")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):       # table-valued function / file path literal
            raise SQLValidationError("Table functions and file paths are not allowed", fatal=True, rule="table_function")
        if t.args.get("db") or t.args.get("catalog"):
            raise SQLValidationError("Qualified (schema/catalog) table names are not allowed", fatal=True, rule="qualified_table")
        name = t.name.lower()
        if name not in cte_names and name not in allowed_tables:
            raise SQLValidationError(f"Unknown or disallowed table: {name}. Allowed: {sorted(allowed_tables)}",
                                     rule="unknown_table")

    if columns is not None:
        from .schema_check import find_schema_hallucinations
        bad = find_schema_hallucinations(tree, columns)
        if bad:
            raise SQLValidationError("Unknown table/column(s): " + ", ".join(bad), rule="unknown_column")

    if block_pii:
        _check_pii(tree)

    if isinstance(tree, exp.Select):
        limit = tree.args.get("limit")
        if limit is None:
            tree = tree.limit(max_rows)
        else:
            try:
                if int(limit.expression.this) > max_rows:
                    tree = tree.limit(max_rows)
            except (ValueError, AttributeError, TypeError):
                tree = tree.limit(max_rows)
    else:
        tree = exp.select("*").from_(tree.subquery("q")).limit(max_rows)
    return tree.sql(dialect=dialect)


def _check_pii(tree: exp.Expression) -> None:
    """Block row-level listing of customer identifiers (no aggregation anywhere in the query)."""
    if tree.find(*AGG_NODES) or tree.find(exp.Group):
        return
    tables = {t.name.lower() for t in tree.find_all(exp.Table)}
    if tree.find(exp.Star) and tables & PII_TABLES:
        raise SQLValidationError("SELECT * on customer data is not allowed; select specific non-identifying columns "
                                 "or aggregate.", fatal=True, rule="pii")
    # only inspect projected columns (not join keys / filters)
    for sel in [tree] if isinstance(tree, exp.Select) else list(tree.find_all(exp.Select)):
        for proj in sel.expressions:
            for c in proj.find_all(exp.Column):
                if c.name.lower() in PII_COLUMNS:
                    raise SQLValidationError(
                        f"Listing individual customer identifiers ({c.name}) is not allowed; aggregate instead.",
                        fatal=True, rule="pii")
