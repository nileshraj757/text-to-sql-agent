import numpy as np, pandas as pd
from eval.compare import has_top_level_order, results_match, superset_match

def df(rows, cols=None):
    return pd.DataFrame(rows, columns=cols)

def test_column_order_and_names_ignored():
    assert results_match(df([(1, "a"), (2, "b")], ["x", "y"]), df([("a", 1), ("b", 2)], ["p", "q"]))

def test_row_order_matters_only_when_ordered():
    g, p = df([(1,), (2,)]), df([(2,), (1,)])
    assert results_match(g, p, ordered=False)
    assert not results_match(g, p, ordered=True)

def test_nulls_equal_and_floats_rounded():
    assert results_match(df([(None, 1.004)]), df([(np.nan, 1.0)]))
    assert not results_match(df([(1.0,)]), df([(1.1,)]))

def test_duplicates_keep_multiplicity():
    assert not results_match(df([(1,), (1,), (2,)]), df([(1,), (2,), (2,)]))

def test_shape_strict_but_superset_lenient():
    g, p = df([(1,), (2,)]), df([(1, "x"), (2, "y")])
    assert not results_match(g, p) and superset_match(g, p)

def test_rtol():
    assert results_match(df([(100.0,)]), df([(100.4,)]), rtol=0.01)
    assert not results_match(df([(100.0,)]), df([(105,)]), rtol=0.01)

def test_order_detection():
    assert has_top_level_order("SELECT a FROM t ORDER BY a")
    assert not has_top_level_order("SELECT a FROM (SELECT a FROM t ORDER BY a)")
