"""Cheap first filter (never the only defense): length cap + obvious instruction-override patterns."""
import re

PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |any |the )?(previous|prior|above|your) (instructions|rules)",
    r"(reveal|print|show|output|repeat) (me )?(your|the) (system )?(prompt|instructions)",
    r"you are now (in )?(admin|developer|dan|root|god)",
    r"(admin|developer|debug|sudo) mode",
    r"(disable|bypass|turn off|ignore) (your |the )?(safety|security|guard ?rails?|validation|filters?|restrictions?)",
    r"jailbreak",
]
_RE = [re.compile(p, re.I) for p in PATTERNS]


def check_input(question: str, max_chars: int = 500) -> tuple[bool, str]:
    """Return (ok, reason)."""
    q = (question or "").strip()
    if not q:
        return False, "Empty question."
    if len(q) > max_chars:
        return False, f"Question too long (max {max_chars} characters)."
    for r in _RE:
        if r.search(q):
            return False, "Request looks like an attempt to override the assistant's instructions."
    return True, ""
