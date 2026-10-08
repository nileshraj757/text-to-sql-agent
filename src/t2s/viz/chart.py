import datetime as _dt
import decimal
import pandas as pd
import plotly.express as px

MAX_BARS = 40
TEMPLATE = "plotly_white"
HUE = "#2a6fb0"


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """DuckDB hands back Decimal and date objects (object dtype); make them numeric/datetime so charts work."""
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object:
            s = df[c].dropna()
            if s.empty:
                continue
            if all(isinstance(v, decimal.Decimal) for v in s):
                df[c] = df[c].astype(float)
            elif all(isinstance(v, (_dt.date, _dt.datetime)) for v in s):
                df[c] = pd.to_datetime(df[c])
    return df


def _split(df):
    num = df.select_dtypes("number").columns.tolist()
    dt = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    cat = [c for c in df.columns if c not in num and c not in dt]
    return num, dt, cat


def choose_chart(df: pd.DataFrame) -> str:
    if df.empty:
        return "table"
    if df.shape == (1, 1):
        return "metric"
    num, dt, cat = _split(df)
    if dt and num:
        return "line"
    if len(cat) == 1 and num and df.shape[0] <= MAX_BARS:
        return "bar"
    if len(cat) == 2 and num and df[cat[1]].nunique() <= 8 and df[cat[0]].nunique() <= MAX_BARS:
        return "bar"                                   # grouped bars
    if len(num) == 2 and not cat:
        return "scatter"
    return "table"


def available_kinds(df: pd.DataFrame) -> list[str]:
    """Chart types that make sense for this result (the UI lets the user switch)."""
    num, dt, cat = _split(df)
    kinds = []
    if num and (cat or dt):
        kinds.append("bar")
    if num and (dt or cat):
        kinds.append("line")
    if len(num) >= 2:
        kinds.append("scatter")
    return kinds


def make_figure(df: pd.DataFrame, kind: str):
    num, dt, cat = _split(df)
    common = dict(template=TEMPLATE)
    fig = None
    if kind == "line" and num and (dt or cat):
        x = dt[0] if dt else cat[0]
        color = next((c for c in cat if c != x and df[c].nunique() <= 12), None)
        if color:
            fig = px.line(df, x=x, y=num[0], color=color, markers=True, **common)
        else:
            fig = px.line(df, x=x, y=num, markers=True, color_discrete_sequence=[HUE], **common)
    elif kind == "bar" and num and (cat or dt):
        x = cat[0] if cat else dt[0]
        color = cat[1] if len(cat) > 1 and df[cat[1]].nunique() <= 8 else None
        if color:
            fig = px.bar(df, x=x, y=num[0], color=color, barmode="group", **common)
        else:
            fig = px.bar(df, x=x, y=num[0], color_discrete_sequence=[HUE], **common)
    elif kind == "scatter" and len(num) >= 2:
        fig = px.scatter(df, x=num[0], y=num[1], color_discrete_sequence=[HUE], **common)
    if fig is not None:
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), legend_title_text="")
    return fig
