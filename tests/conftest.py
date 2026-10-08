import json, sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))

from t2s.guardrails.executor import make_connection
from t2s.guardrails.schema_check import load_columns
from t2s.utils.config import DB_PATH


@pytest.fixture(scope="session")
def con():
    if not DB_PATH.exists():
        pytest.skip("database not built: python scripts/build_db.py")
    return make_connection(DB_PATH)


@pytest.fixture(scope="session")
def cols(con):
    return load_columns(con)
