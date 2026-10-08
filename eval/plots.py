"""README figures from measured results only. Skips any figure whose inputs do not exist yet.
One hue, no dual axes, direct labels, thin marks (see dataviz guidance)."""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
RES, OUT = ROOT / "eval/results", ROOT / "docs/figures"
INK, MUTED, HUE = "#1f2328", "#6b7280", "#2a6fb0"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": MUTED,
                     "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})


def ladder():
    p = RES / "ladder.json"
    if not p.exists():
        return
    d = json.loads(p.read_text())
    keys = [k for k in ["1", "2", "3", "4", "5", "6", "6b"] if k in d]
    if not keys:
        return
    fig, ax = plt.subplots(figsize=(7, 3.6))
    vals = [100 * d[k]["execution_accuracy"] for k in keys]
    bars = ax.bar([f"Step {k}" for k in keys], vals, color=HUE, width=0.55)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.0f}%", ha="center", fontsize=9)
    ax.set_ylim(0, 105); ax.set_ylabel("Execution accuracy (%)"); ax.set_title("Experiment ladder (dev split)", loc="left")
    ax.grid(axis="y", color="#e5e7eb", lw=0.6); ax.set_axisbelow(True)
    OUT.mkdir(parents=True, exist_ok=True); fig.tight_layout(); fig.savefig(OUT / "ladder.png", dpi=160); plt.close(fig)


def tier_heatmap():
    p = RES / "ladder.json"
    if not p.exists():
        return
    d = json.loads(p.read_text())
    keys = [k for k in ["1", "2", "3", "5", "6"] if k in d]
    tiers = ["single_table", "aggregation", "join", "multi_join", "subquery_cte", "window", "date_logic"]
    if not keys:
        return
    M = np.array([[100 * d[k]["by_tier"].get(t, np.nan) for k in keys] for t in tiers])
    fig, ax = plt.subplots(figsize=(6, 3.8))
    im = ax.imshow(M, cmap="Blues", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(keys)), [f"Step {k}" for k in keys]); ax.set_yticks(range(len(tiers)), tiers)
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            if not np.isnan(M[i, j]):
                ax.text(j, i, f"{M[i,j]:.0f}", ha="center", va="center", color="white" if M[i, j] > 60 else INK, fontsize=9)
    ax.set_title("Accuracy (%) by tier", loc="left"); fig.colorbar(im, ax=ax, shrink=0.8)
    OUT.mkdir(parents=True, exist_ok=True); fig.tight_layout(); fig.savefig(OUT / "tier_heatmap.png", dpi=160); plt.close(fig)


def retries():
    pts = []
    for r in [0, 1, 2, 3]:
        p = RES / f"ablations/max_retries_{r}.json"
        if p.exists():
            m = json.loads(p.read_text()); pts.append((r, 100 * m["execution_accuracy"], m["cost_per_query_usd"]))
    if len(pts) < 2:
        return
    fig, axs = plt.subplots(1, 2, figsize=(8, 3.2))   # two charts, not a dual axis
    axs[0].plot([p[0] for p in pts], [p[1] for p in pts], color=HUE, lw=2, marker="o", ms=6); axs[0].set_title("Accuracy vs retries", loc="left"); axs[0].set_ylabel("Execution accuracy (%)")
    axs[1].plot([p[0] for p in pts], [p[2] for p in pts], color=HUE, lw=2, marker="o", ms=6); axs[1].set_title("Cost vs retries", loc="left"); axs[1].set_ylabel("$/query")
    for a in axs: a.set_xlabel("max retries"); a.set_xticks([p[0] for p in pts]); a.grid(axis="y", color="#e5e7eb", lw=0.6)
    OUT.mkdir(parents=True, exist_ok=True); fig.tight_layout(); fig.savefig(OUT / "retries.png", dpi=160); plt.close(fig)


def redteam():
    p = RES / "redteam_offline.json"
    if not p.exists():
        return
    r = json.loads(p.read_text())
    cats = r["by_category"]
    names = list(cats)
    frac = [int(v.split("/")[0]) / int(v.split("/")[1]) * 100 for v in cats.values()]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    ax.barh(names[::-1], frac[::-1], color=HUE, height=0.55)
    for y, (n, v) in enumerate(zip(names[::-1], list(cats.values())[::-1])):
        ax.text(min(frac[::-1][y], 100) + 1, y, v, va="center", fontsize=9)
    ax.set_xlim(0, 115); ax.set_xlabel("Attacks defended (%)"); ax.set_title("Red-team, offline layer isolation", loc="left")
    OUT.mkdir(parents=True, exist_ok=True); fig.tight_layout(); fig.savefig(OUT / "redteam.png", dpi=160); plt.close(fig)


if __name__ == "__main__":
    for f in (ladder, tier_heatmap, retries, redteam):
        f()
    print("figures:", sorted(p.name for p in OUT.glob("*.png")))
