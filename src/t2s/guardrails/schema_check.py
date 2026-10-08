"""Schema-hallucination detection: does the SQL reference tables/columns that don't exist?"""
from __future__ import annotations
import sqlglot
from sqlglot import exp


def load_columns(con) -> dict[str, set[str]]:
    rows = con.execute("SELECT table_name, column_name FROM information_schema.columns "
                       "WHERE table_schema='main'").fetchall()
    out: dict[str, set[str]] = {}
    for t, c in rows:
        out.setdefault(t.lower(), set()).add(c.lower())
    return out


def find_schema_hallucinations(tree_or_sql, columns: dict[str, set[str]], dialect="duckdb") -> list[str]:
    """Return a list of 'table' / 'alias.column' / 'column' strings that don't resolve. Empty = clean.
    Unparseable SQL returns [] (that is a syntax error, counted separately)."""
    if isinstance(tree_or_sql, str):
        try:
            tree = sqlglot.parse_one(tree_or_sql, read=dialect)
        except sqlglot.errors.SqlglotError:
            return []
    else:
        tree = tree_or_sql
    if tree is None:
        return []
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    alias_to_table: dict[str, str] = {}
    bad: list[str] = []
    for t in tree.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            continue
        name = t.name.lower()
        if name in cte_names:
            continue
        if name not in columns:
            bad.append(name)
            continue
        alias_to_table[(t.alias or name).lower()] = name
    if bad:
        return sorted(set(bad))
    aliases = {a.alias.lower() for a in tree.find_all(exp.Alias) if a.alias}
    for node in tree.find_all(exp.CTE, exp.Subquery, exp.Table):   # derived-table aliases and CTE column lists
        if node.alias:
            aliases.add(node.alias.lower())
        for ce in (node.args.get("alias").args.get("columns") or []) if node.args.get("alias") else []:
            aliases.add(ce.name.lower())
    derived_cols = set()   # output columns of CTEs/subqueries are visible to outer queries
    for q in tree.find_all(exp.CTE, exp.Subquery):
        inner = q.this if isinstance(q, exp.CTE) else q.this
        if isinstance(inner, exp.Query):
            derived_cols |= {n.lower() for n in inner.named_selects}
    all_cols = set().union(*columns.values())
    for c in tree.find_all(exp.Column):
        name = c.name.lower()
        if isinstance(c.this, exp.Star) or not name:
            continue
        qual = c.table.lower()
        if qual in alias_to_table:
            if name not in columns[alias_to_table[qual]] and name not in aliases and name not in derived_cols:
                bad.append(f"{qual}.{name}")
        elif qual:
            if qual not in aliases and qual not in cte_names:
                bad.append(f"{qual}.{name}")   # unknown qualifier
        elif name not in all_cols and name not in aliases and name not in derived_cols:
            bad.append(name)
    return sorted(set(bad))
