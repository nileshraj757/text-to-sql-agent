import os
from t2s.utils.config import _load_dotenv

def test_dotenv_ignores_inline_comments_and_empty_values(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("T2S_X1=   # nothing here\nT2S_X2=abc  # trailing\nT2S_X3=\"q\"\n# comment\nT2S_X4=http://h:1/v1\n")
    for k in ("T2S_X1", "T2S_X2", "T2S_X3", "T2S_X4"):
        monkeypatch.delenv(k, raising=False)
    _load_dotenv(f)
    assert "T2S_X1" not in os.environ and os.environ["T2S_X2"] == "abc"
    assert os.environ["T2S_X3"] == "q" and os.environ["T2S_X4"] == "http://h:1/v1"
    for k in ("T2S_X2", "T2S_X3", "T2S_X4"):
        monkeypatch.delenv(k, raising=False)


def test_shipped_template_parses_cleanly(tmp_path, monkeypatch):
    """The real .env.example (with a fake key pasted in) must yield exactly that key and no comment garbage."""
    from pathlib import Path
    txt = (Path(__file__).resolve().parents[1] / ".env.example").read_text().replace("GROQ_API_KEY=", "GROQ_API_KEY=fake-key-123 ", 1)
    f = tmp_path / ".env"; f.write_text(txt)
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "T2S_FALLBACK", "T2S_PROVIDER", "T2S_MODEL", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    _load_dotenv(f)
    assert os.environ["GROQ_API_KEY"] == "fake-key-123"
    assert "GEMINI_API_KEY" not in os.environ and "T2S_FALLBACK" not in os.environ      # empty -> unset, not "# comment"
    assert os.environ["T2S_PROVIDER"] == "groq" and os.environ["T2S_MODEL"] == "openai/gpt-oss-120b"
    for k in ("GROQ_API_KEY", "T2S_PROVIDER", "T2S_MODEL", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
