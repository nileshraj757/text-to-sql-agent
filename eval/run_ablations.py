"""One-variable-at-a-time ablations on the final config (dev split). Needs a real LLM; results cached by prompt hash."""
import argparse, json, subprocess, sys, tempfile
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "eval/results/ablations"
GRID = {"fewshot_k": [0, 1, 3, 5, 8], "samples": [False, True], "glossary": [False, True],
        "max_retries": [0, 1, 2, 3], "temperature": [0.0, 0.2, 0.5], "fewshot_mode": ["static", "retrieved"]}
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--base", default="configs/best.yaml"); ap.add_argument("--split", default="dev")
    ap.add_argument("--vars", nargs="*", default=list(GRID)); a = ap.parse_args()
    RES.mkdir(parents=True, exist_ok=True)
    base = yaml.safe_load(open(ROOT / a.base))
    for var in a.vars:
        for val in GRID[var]:
            cfg = {**base, var: val, "name": f"abl_{var}_{val}"}
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as t:
                yaml.safe_dump(cfg, t)
            out = RES / f"{var}_{val}.json"
            subprocess.run([sys.executable, str(ROOT / "eval/run_eval.py"), "--config", t.name, "--split", a.split, "--out", str(out)], check=False)
    rows = []
    for var in GRID:
        for val in GRID[var]:
            p = RES / f"{var}_{val}.json"
            if p.exists():
                m = json.loads(p.read_text()); rows.append((var, val, m["execution_accuracy"], m["cost_per_query_usd"], m["latency_p50_s"]))
    L = ["| Variable | Value | Exec acc. | $/query | p50 latency (s) |", "|---|---|---|---|---|"] + [f"| {v} | {x} | {100*e:.1f}% | {c:.5f} | {l:.2f} |" for v, x, e, c, l in rows]
    (ROOT / "eval/results/ablations.md").write_text("\n".join(L) + "\n"); print("\n".join(L))
