"""Tells you exactly what is missing. Run:  python scripts/check_setup.py"""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
ok = True


def line(good, msg, fix=""):
    global ok
    ok &= bool(good) or fix == "optional"
    print(("[ok]   " if good else "[WARN] " if fix == "optional" else "[FAIL] ") + msg + ("" if good or fix == "optional" else f"\n       fix: {fix}"))


line(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]} (need 3.10+)", "install Python 3.10 or newer")
try:
    import duckdb, sqlglot, streamlit, pandas, plotly  # noqa: F401
    line(True, "Python packages installed")
except ImportError as e:
    line(False, f"missing package: {e.name}", 'pip install -e ".[dev]"')
from t2s.utils.config import DB_PATH, ROOT as R  # loads .env
line(DB_PATH.exists(), f"Olist database at {DB_PATH.relative_to(R)}", "./scripts/download_data.sh && python scripts/build_db.py")
line((R / ".env").exists(), ".env file present", "cp .env.example .env   (then add a key)")
keys = {k: bool(os.environ.get(k)) for k in ("GROQ_API_KEY", "GEMINI_API_KEY")}
prov = os.environ.get("T2S_PROVIDER", "groq")
need = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}.get(prov)
if need:
    line(keys[need], f"{need} set (provider={prov})" if keys[need] else
         f"{need} is not set (provider={prov}): add it to .env and restart, or set T2S_PROVIDER to a provider you have a key for", "" if keys[need] else "optional")
else:
    line(True, f"provider={prov} (no key variable required)")
if not any(keys.values()) and prov in ("groq", "gemini"):
    print("       -> without a key the app still starts, in DEMO mode (sample questions only; uploads disabled)")
if DB_PATH.exists():
    try:
        from t2s.api.service import AskService
        s = AskService()
        print(f"[ok]   app mode: {s.mode.upper()}  (provider={s.cfg.provider}, model={s.cfg.model})")
        if s.mode == "live":
            r = s.ask("How many sellers are there?", "check")
            line(r["status"] == "ok" and r["rows"] == [[3095]], "live test question answered correctly (3095 sellers)" if r["status"] == "ok" else f"live test failed: {r['message']}",
                 "check the key, T2S_MODEL name, and your network")
    except Exception as e:  # noqa: BLE001
        line(False, f"app failed to start: {e}", "see README > Troubleshooting")
print("\nAll good. Start the app:  streamlit run app/streamlit_app.py" if ok else "\nFix the [FAIL] items above, then re-run this script.")
sys.exit(0 if ok else 1)
