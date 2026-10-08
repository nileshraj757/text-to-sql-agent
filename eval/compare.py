"""Result-set comparison for execution accuracy. Policies are documented in docs/eval_policy.md."""
from __future__ import annotations
from collections import Counter
from itertools import permutations
import numpy as np
import pandas as pd
import sqlglot


def _canon(v, nd):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float, np.integer, np.floating)):
        return round(float(v), nd)
    if isinstance(v, (pd.Timestamp,)):
        return str(v)
    return str(v).strip()


def _rows(df, nd):
    return [tuple(_canon(v, nd) for v in tup) for tup in df.itertuples(index=False, name=None)]


def _close(a, b, rtol):
    if a is None or b is None:
        return a is b
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= max(0.0, rtol * max(abs(a), abs(b))) + 1e-9
    return a == b


def results_match(gold: pd.DataFrame, pred: pd.DataFrame, ordered=False, nd=2, max_perm_cols=6, rtol=0.0) -> bool:
    """Column names ignored; column ORDER ignored (permutations); NULL == NULL; floats rounded to `nd`
    (optionally within relative tolerance `rtol`). Row order only matters when `ordered`. Shape must match (strict)."""
    if gold.shape != pred.shape:
        return False
    g = _rows(gold, nd)
    n = gold.shape[1]
    perms = permutations(range(n)) if n <= max_perm_cols else [tuple(range(n))]
    for p in perms:
        pr = _rows(pred.iloc[:, list(p)], nd)
        if rtol:
            if ordered:
                if all(all(_close(a, b, rtol) for a, b in zip(x, y)) for x, y in zip(pr, g)):
                    return True
            else:
                key = lambda r: tuple((1, x) if isinstance(x, str) else (0, round(x, 0)) if x is not None else (2, 0) for x in r)  # noqa: E731
                if all(all(_close(a, b, rtol) for a, b in zip(x, y))
                       for x, y in zip(sorted(pr, key=key), sorted(g, key=key))):
                    return True
        elif (pr == g) if ordered else (Counter(pr) == Counter(g)):
            return True
    return False


def has_top_level_order(sql: str, dialect="duckdb") -> bool:
    return sqlglot.parse_one(sql, read=dialect).args.get("order") is not None


def superset_match(gold: pd.DataFrame, pred: pd.DataFrame, ordered=False, nd=2) -> bool:
    """Lenient secondary metric: pred may contain extra columns as long as some column subset matches gold."""
    if pred.shape[0] != gold.shape[0] or pred.shape[1] < gold.shape[1]:
        return False
    from itertools import combinations
    for idx in combinations(range(pred.shape[1]), gold.shape[1]):
        if results_match(gold, pred.iloc[:, list(idx)], ordered, nd):
            return True
    return False
