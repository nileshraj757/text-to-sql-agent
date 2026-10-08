#!/usr/bin/env bash
# One-command setup + launch.   ./scripts/quickstart.sh          (setup, check, start UI)
#                               ./scripts/quickstart.sh --no-run (setup and check only)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
[ -d .venv ] || { echo "==> creating virtualenv"; $PY -m venv .venv; }
. .venv/bin/activate
echo "==> installing dependencies"; pip install -q -e ".[dev]"
[ -f data/db/olist.duckdb ] || { echo "==> downloading Olist CSVs + building database"; ./scripts/download_data.sh >/dev/null; python scripts/build_db.py; }
[ -f .env ] || { cp .env.example .env; echo "==> created .env  -> open it and paste a GROQ_API_KEY or GEMINI_API_KEY (optional: app runs in demo mode without)"; }
python scripts/check_setup.py || true
[ "${1:-}" = "--no-run" ] || { echo "==> starting UI on http://localhost:8502"; exec streamlit run app/streamlit_app.py --server.port 8502; }
