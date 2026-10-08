"""Streamlit UI. In-process by default; set T2S_API_URL to use the FastAPI backend instead."""
import os, sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
import streamlit as st

from t2s.viz.chart import choose_chart, make_figure, normalize_df, available_kinds  # noqa: E402

st.set_page_config(page_title="Text-to-SQL Analytics Agent", layout="wide")
API = os.environ.get("T2S_API_URL")
OLIST, UPLOAD = "Olist e-commerce (sample data)", "My uploaded data"


# ---- backend access (in-process or HTTP) ---------------------------------------------------------
@st.cache_resource
def get_service():
    from t2s.api.service import AskService
    return AskService()


def backend_mode() -> str:
    if API:
        import requests
        try:
            return requests.get(f"{API}/health", timeout=5).json().get("mode", "live")
        except Exception:  # noqa: BLE001
            return "live"
    return get_service().mode


def ask(q: str, sid: str, dataset_id: str | None) -> dict:
    if API:
        import requests
        r = requests.post(f"{API}/ask", json={"question": q, "session_id": sid, "dataset_id": dataset_id}, timeout=180)
        return r.json() if r.ok else {"status": "failed", "message": f"API error {r.status_code}: {r.text[:200]}"}
    return get_service().ask(q, sid, dataset_id)


def samples() -> list[dict]:
    if API:
        import requests
        return requests.get(f"{API}/samples", timeout=10).json()
    from t2s.api.service import load_samples
    return load_samples()


def upload(files: list[tuple[str, bytes]]) -> dict:
    """Returns dataset info or raises ValueError with a user-readable message."""
    if API:
        import requests
        r = requests.post(f"{API}/upload", files=[("files", (n, b)) for n, b in files], timeout=300)
        if not r.ok:
            raise ValueError(r.json().get("detail", r.text[:200]))
        return r.json()
    from t2s.agent.dataset import UploadError
    try:
        return get_service().create_dataset(files)
    except UploadError as e:
        raise ValueError(str(e))


def preview(ds_id: str, table: str) -> pd.DataFrame:
    if API:
        import requests
        d = requests.get(f"{API}/datasets/{ds_id}/preview/{table}", timeout=30).json()
    else:
        d = get_service().dataset_preview(ds_id, table)
    return pd.DataFrame(d["rows"], columns=d["columns"])


# ---- state ---------------------------------------------------------------------------------------
ss = st.session_state
ss.setdefault("sid", uuid.uuid4().hex[:8])
ss.setdefault("dataset", None)          # info dict of the uploaded dataset
ss.setdefault("result", None)           # {"q", "source", "r"}: persisted so widgets (chart toggle) don't wipe it
ss.setdefault("uploader_n", 0)
mode = backend_mode()


def run_question(q: str):
    q = (q or "").strip()
    if not q:
        return
    use_upload = ss.get("source") == UPLOAD and ss.dataset
    with st.spinner("Thinking..."):
        r = ask(q, ss.sid, ss.dataset["id"] if use_upload else None)
    ss.result = {"q": q, "source": UPLOAD if use_upload else OLIST, "r": r}


def pick_sample(q: str):
    ss.q = q
    ss.pending = q


# ---- sidebar -------------------------------------------------------------------------------------
st.title("Text-to-SQL Analytics Agent")
with st.sidebar:
    st.subheader("Data source")
    source = st.radio("Query", [OLIST, UPLOAD], key="source", label_visibility="collapsed")
    if source == UPLOAD:
        if mode != "live":
            st.warning("Querying uploaded data needs an LLM, and no API key is configured on this server.")
        files = st.file_uploader("Upload CSV, TSV, Excel, Parquet or JSON files (up to 8 files, 50 MB each)",
                                 type=["csv", "tsv", "txt", "xlsx", "xls", "parquet", "json", "jsonl"],
                                 accept_multiple_files=True, key=f"uploader_{ss.uploader_n}")
        c1, c2 = st.columns(2)
        if c1.button("Load data", type="primary", disabled=not files, width="stretch"):
            with st.spinner("Reading files..."):
                try:
                    ss.dataset = upload([(f.name, f.getvalue()) for f in files])
                    ss.result = None
                except ValueError as e:
                    st.error(str(e))
        if c2.button("Clear", disabled=not ss.dataset, width="stretch"):
            ss.dataset, ss.result = None, None
            ss.uploader_n += 1
            st.rerun()
        if ss.dataset:
            st.success(f"Loaded {len(ss.dataset['tables'])} table(s)")
            for t in ss.dataset["tables"]:
                with st.expander(f"{t['name']}  ({t['rows']:,} rows)"):
                    st.caption(f"from {t['source']}")
                    st.dataframe(pd.DataFrame(t["columns"]), hide_index=True, height=180)
                    st.dataframe(preview(ss.dataset["id"], t["name"]), hide_index=True)
            st.caption("Names are normalised to snake_case so the model can use them. "
                       "Your data stays on this server and is only read through a read-only connection.")
    else:
        st.subheader("Sample questions")
        for s in samples():
            st.button(s["question"], key="s_" + s["question"], on_click=pick_sample, args=(s["question"],))
        st.caption("In demo mode (no LLM key) only these are answered." if mode != "live" else
                   "Olist Brazilian e-commerce, 9 tables. Questions are logged for evaluation.")

if source == UPLOAD and not ss.dataset:
    st.info("Upload one or more files in the sidebar, click **Load data**, then ask questions about them. "
            "Several files become several tables; columns with the same name (e.g. `customer_id`) are suggested as join keys.")
    st.stop()

# ---- ask -----------------------------------------------------------------------------------------
if ss.get("pending"):
    run_question(ss.pop("pending"))
with st.form("ask_form", clear_on_submit=False):
    q = st.text_input("Ask a question about the data", key="q", max_chars=500,
                      placeholder="e.g. How many orders were placed in 2017?" if source == OLIST
                      else "e.g. What is the total sales by region?")
    submitted = st.form_submit_button("Ask", type="primary")
if submitted:
    run_question(q)

# ---- render the persisted result -----------------------------------------------------------------
res = ss.result
if res and res["source"] == source:
    r = res["r"]
    status = r["status"]
    st.caption(f"Q: {res['q']}")
    if status == "ok":
        df = normalize_df(pd.DataFrame(r["rows"], columns=r["columns"]))
        if r.get("mode") == "demo":
            st.info("Demo mode: the SQL below is pre-written (no model key configured).")
        if r.get("explanation"):
            e = r["explanation"]
            st.write(e["text"])
            if not e["grounded"]:
                st.warning(f"Unverified numbers in this explanation: {e['ungrounded']}")
        auto = choose_chart(df)
        kinds = available_kinds(df)
        if auto == "metric":
            st.metric(str(r["columns"][0]), r["rows"][0][0])
            view = "Table"
        elif kinds:
            c1, c2, _ = st.columns([1, 1, 3])
            view = c1.radio("View", ["Chart", "Table"], horizontal=True, key="view")
            kind = auto if auto in kinds else kinds[0]
            if view == "Chart" and len(kinds) > 1:
                kind = c2.selectbox("Chart type", kinds, index=kinds.index(kind), key=f"kind_{auto}")
            if view == "Chart":
                fig = make_figure(df, kind)
                if fig is not None:
                    st.plotly_chart(fig, width="stretch")
                else:
                    st.info("No chart fits this result; showing the table.")
                    view = "Table"
        else:
            view = "Table"
            if len(df) > 1:
                st.caption("This result has no numeric column to chart, so it is shown as a table.")
        if view == "Table" or auto == "metric":
            st.dataframe(df, width="stretch", hide_index=True)
        st.caption(f"{len(df)} rows{' (truncated by row cap)' if r.get('truncated') else ''} - "
                   f"{r['latency_ms']} ms - attempts: {len(r['attempts'])}")
        if r["assumptions"]:
            st.markdown("**Assumptions**\n" + "\n".join(f"- {a}" for a in r["assumptions"]))
        with st.expander("SQL"):
            st.code(r["sql"], language="sql")
        if len(r["attempts"]) > 1:
            with st.expander("Self-correction attempts"):
                st.json(r["attempts"])
    elif status == "clarify":
        st.info(f"Clarification needed: {r['message']}")
    elif status == "refused":
        st.warning(f"Can't answer: {r['message']}")
    elif status == "blocked":
        st.error(f"Blocked by {r.get('blocked_by')}: {r['message']}")
    else:
        st.error(r.get("message") or "Failed")
