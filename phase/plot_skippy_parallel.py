"""Boxplot of final best-metric by condition for the 5xxx skippy_parallel sweep.

Renders paper Figure 4 (§5.4): skippy_only (best-of-1) vs skippy_parallel
(best-of-2 undirected) vs bishop (best-of-2 Bishop-directed), all under
SEARCH/REPLACE. Distributions are the same final best_ever_metric values
verified by analyze_skippy_parallel.py; metric shown in milliseconds.

Significance brackets annotate the two pre-registered adjacent comparisons:
  skippy_parallel vs skippy_only  (secondary, p = 0.072, n.s.)
  bishop vs skippy_parallel       (PRIMARY,   p = 0.00053)
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RESULTS = Path(__file__).resolve().parent / "results"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# (label, condition dir prefix, seed range, box color)
CONDITIONS = [
    ("skippy_only\n(best-of-1)",            "skippy_only",     range(5001, 5011), "C0"),
    ("skippy_parallel\n(best-of-2, undirected)", "skippy_parallel", range(5101, 5131), "C1"),
    ("bishop\n(best-of-2, directed)",       "bare_faithful",   range(5201, 5231), "C2"),
]

# (i, j, label, y-offset rank) for significance brackets between box i and j.
BRACKETS = [
    (0, 1, "p = 0.072 (n.s.)", 0),
    (1, 2, "p = 0.00053",      1),
]


def load_finals_ms(cond: str, seeds) -> np.ndarray:
    vals = []
    for s in seeds:
        sj = RESULTS / f"{cond}_{s}" / "summary.json"
        vals.append(float(json.loads(sj.read_text())["best_ever_metric"]) * 1000.0)
    return np.array(vals)


def main() -> None:
    data = [load_finals_ms(c, seeds) for _, c, seeds, _ in CONDITIONS]
    labels = [lbl for lbl, _, _, _ in CONDITIONS]
    colors = [col for _, _, _, col in CONDITIONS]
    positions = list(range(1, len(data) + 1))

    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    bp = ax.boxplot(data, positions=positions, widths=0.55, showfliers=False,
                    patch_artist=True, medianprops=dict(color="black", linewidth=1.6))
    for patch, col in zip(bp["boxes"], colors):
        patch.set_facecolor(col)
        patch.set_alpha(0.35)

    # Raw points, jittered, no extra RNG dependence (deterministic offsets).
    for pos, vals, col in zip(positions, data, colors):
        jitter = (np.arange(len(vals)) - (len(vals) - 1) / 2.0)
        jitter = 0.18 * jitter / max(1, jitter.max() if jitter.max() else 1)
        ax.scatter(pos + jitter, vals, color=col, edgecolor="black",
                   linewidth=0.4, s=26, zorder=5)

    ax.set_xticks(positions)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("final best metric — corpus parse time (ms)\n(lower is better)")
    ax.set_title("Final best metric by condition — 5xxx matched sweep "
                 "(SEARCH/REPLACE in every arm)", fontsize=10)
    ax.grid(axis="y", alpha=0.3)

    # Significance brackets above the boxes.
    ymax = max(v.max() for v in data)
    ymin = min(v.min() for v in data)
    span = ymax - ymin
    base = ymax + 0.06 * span
    step = 0.11 * span
    for i, j, text, rank in BRACKETS:
        y = base + rank * step
        xi, xj = positions[i], positions[j]
        ax.plot([xi, xi, xj, xj], [y, y + 0.02 * span, y + 0.02 * span, y],
                color="black", linewidth=1.0)
        ax.text((xi + xj) / 2.0, y + 0.025 * span, text, ha="center",
                va="bottom", fontsize=8.5)
    ax.set_ylim(ymin - 0.05 * span, base + (len(BRACKETS)) * step + 0.06 * span)

    fig.tight_layout()
    out = PROJECT_ROOT / "final_per_condition_5xxx.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"wrote {out}")
    for lbl, vals in zip(labels, data):
        print(f"  {lbl.splitlines()[0]:<16} n={len(vals):>2} "
              f"median={np.median(vals):.4f} ms  IQR=[{np.percentile(vals,25):.4f}, "
              f"{np.percentile(vals,75):.4f}] ms")


if __name__ == "__main__":
    main()
