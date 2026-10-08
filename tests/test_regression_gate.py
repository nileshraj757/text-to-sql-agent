"""The CI gate must actually fail when the pipeline is broken (a deliberately broken prompt / validator)."""
import json, subprocess, sys
from pathlib import Path
import pytest
from eval.run_eval import aggregate, load_testset, oracle_llm, run
from t2s.utils.config import AgentConfig

ROOT = Path(__file__).resolve().parents[1]
CFG = AgentConfig.load(ROOT / "configs/best.yaml")


def gate(metrics, tmp_path):
    f = tmp_path / "m.json"; f.write_text(json.dumps(metrics))
    return subprocess.run([sys.executable, str(ROOT / "eval/check_thresholds.py"), str(f), str(ROOT / "eval/thresholds.json")]).returncode


def evaluate():
    ts = load_testset("all", "smoke")
    all_ts = [json.loads(l) for l in open(ROOT / "eval/testset_v1.jsonl")]
    return aggregate(run(CFG, ts, oracle_llm(all_ts), "t"))


def test_healthy_pipeline_passes_gate(con, tmp_path):
    assert gate(evaluate(), tmp_path) == 0


def test_broken_prompt_fails_gate(con, tmp_path, monkeypatch):
    import t2s.agent.pipeline as pl
    monkeypatch.setattr(pl, "build_user_prompt", lambda q, *a, **k: "SCHEMA: ...")   # question dropped from prompt
    assert gate(evaluate(), tmp_path) == 1


def test_overblocking_validator_fails_gate(con, tmp_path, monkeypatch):
    import t2s.agent.pipeline as pl
    from t2s.guardrails.validator import SQLValidationError
    def always_block(*a, **k):
        raise SQLValidationError("blocked", fatal=True)
    monkeypatch.setattr(pl, "validate_and_rewrite", always_block)
    assert gate(evaluate(), tmp_path) == 1
