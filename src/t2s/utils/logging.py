import json, os, threading, time
from pathlib import Path
from ..utils.config import ROOT

_lock = threading.Lock()
LOG_PATH = Path(os.environ.get("T2S_AUDIT_LOG", ROOT / "logs/audit.jsonl"))


def audit_event(event: dict) -> None:
    """Append one JSON line (timestamp, session, question, SQL, verdict, rows, latency, outcome)."""
    event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
    try:
        with _lock:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_PATH, "a") as f:
                f.write(json.dumps(event, default=str) + "\n")
    except OSError:
        pass  # logging must never break a request
