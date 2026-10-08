"""Deterministic number-grounding check for explanations."""
import re
import numpy as np


def _numeric_pool(df) -> list[float]:
    vals = [float(v) for v in df.to_numpy().ravel()
            if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) and v == v]
    pool = list(vals)
    pool.append(float(len(df)))
    for c in df.select_dtypes("number").columns:       # derived values the generator may legitimately state
        s = df[c].dropna().astype(float)
        if s.empty:
            continue
        tot = float(s.sum())
        pool += [tot, float(s.mean()), float(s.min()), float(s.max()), float(s.max() - s.min())]
        if tot:
            pool += [100.0 * v / tot for v in s]
        for a, b in zip(s.iloc[:-1], s.iloc[1:]):
            pool += [float(b - a), abs(float(b - a))]
            if a:
                pool += [100.0 * (b - a) / a, abs(100.0 * (b - a) / a)]
        if len(s) > 1 and s.iloc[0]:
            pool += [float(s.iloc[-1] / s.iloc[0]), float(s.iloc[0] / s.iloc[-1]) if s.iloc[-1] else 0.0]
    return pool


def ungrounded_numbers(text: str, df, rel_tol: float = 0.01) -> list[str]:
    """Numbers in `text` that appear neither in the rows nor among derived values (sums, shares, deltas).
    Whitelist: calendar years and small integers up to the row count (ranks, 'top 5')."""
    pool = _numeric_pool(df)
    bad = []
    for m in re.findall(r"-?\d[\d,]*\.?\d*", text):
        try:
            x = float(m.replace(",", "").rstrip("."))
        except ValueError:
            continue
        if 1990 <= x <= 2100 and x == int(x):
            continue
        if x == int(x) and 0 <= x <= len(df):
            continue
        if not any(abs(abs(x) - abs(p)) <= rel_tol * max(1.0, abs(p)) for p in pool):
            bad.append(m)
    return bad
