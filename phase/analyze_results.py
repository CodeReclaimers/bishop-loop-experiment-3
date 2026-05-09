"""Aggregate per-(condition, seed) summaries into the final writeup data + plots."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import mannwhitneyu

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "phase" / "results"

CONDITIONS = ["skippy_only", "bare_faithful", "steelman"]
SEEDS = [1001, 1002, 1003]


def load_summary(condition: str, seed: int) -> dict | None:
    p = RESULTS_DIR / f"{condition}_{seed}" / "summary.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def aggregate() -> dict:
    by_cond = {c: [] for c in CONDITIONS}
    for c in CONDITIONS:
        for s in SEEDS:
            summary = load_summary(c, s)
            if summary is not None:
                by_cond[c].append(summary)
    return by_cond


def per_condition_stats(summaries: list[dict]) -> dict:
    if not summaries:
        return {}
    finals = [s.get("best_ever_metric", float("inf")) for s in summaries]
    iters = [s.get("iterations_completed", 0) for s in summaries]
    promotes = [s.get("promotions", 0) for s in summaries]
    skippy_wins = [s.get("skippy_arm_wins", 0) for s in summaries]
    bishop_wins = [s.get("bishop_arm_wins", 0) for s in summaries]
    return {
        "n_runs": len(summaries),
        "final_metric_values": finals,
        "final_metric_mean": float(np.mean(finals)),
        "final_metric_std": float(np.std(finals, ddof=1)) if len(finals) > 1 else 0.0,
        "iterations_mean": float(np.mean(iters)),
        "iterations_total": sum(iters),
        "promotions_mean": float(np.mean(promotes)),
        "skippy_arm_wins_total": sum(skippy_wins),
        "bishop_arm_wins_total": sum(bishop_wins),
    }


def pairwise_comparison(summaries_a: list[dict], summaries_b: list[dict]) -> dict:
    if not summaries_a or not summaries_b:
        return {"n_a": len(summaries_a), "n_b": len(summaries_b), "note": "missing data"}
    a = [s.get("best_ever_metric", float("inf")) for s in summaries_a]
    b = [s.get("best_ever_metric", float("inf")) for s in summaries_b]
    try:
        u, p = mannwhitneyu(a, b, alternative="two-sided")
    except Exception as e:
        return {"error": str(e), "a": a, "b": b}
    return {
        "a_values": a,
        "b_values": b,
        "a_mean": float(np.mean(a)),
        "b_mean": float(np.mean(b)),
        "u_statistic": float(u),
        "p_value": float(p),
        "n_a": len(a),
        "n_b": len(b),
        "note": "underpowered with n=3 per side" if min(len(a), len(b)) <= 3 else "",
    }


def plot_trajectories(by_cond: dict, out_path: Path) -> None:
    plt.figure(figsize=(9, 5))
    colors = {"skippy_only": "C0", "bare_faithful": "C1", "steelman": "C2"}
    for cond, summaries in by_cond.items():
        for s in summaries:
            traj = s.get("trajectory", [])
            if not traj:
                continue
            xs = [t["wall_s"] for t in traj]
            ys = [t.get("best_ever_metric") or t.get("metric") for t in traj]
            # cumulative-min in case best_ever_metric isn't set on early entries
            cur = float("inf")
            cumin = []
            for v in ys:
                if v is None:
                    cumin.append(cur)
                    continue
                cur = min(cur, v)
                cumin.append(cur)
            plt.plot(xs, cumin, color=colors[cond], alpha=0.6,
                     label=f"{cond}_{s['seed']}")
    plt.xlabel("wall-clock seconds")
    plt.ylabel("best-ever metric (lower is better)")
    plt.title("Per-condition best metric over time (3 seeds × 3 conditions)")
    plt.legend(fontsize=7, ncol=3)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=130)
    plt.close()


def plot_final_with_errorbars(by_cond: dict, out_path: Path) -> None:
    plt.figure(figsize=(7, 4))
    conditions = list(by_cond.keys())
    xs = list(range(len(conditions)))
    means = []
    stds = []
    individual_xs = []
    individual_ys = []
    for x, c in zip(xs, conditions):
        summaries = by_cond[c]
        finals = [s.get("best_ever_metric", float("inf")) for s in summaries]
        if not finals:
            means.append(0)
            stds.append(0)
            continue
        means.append(float(np.mean(finals)))
        stds.append(float(np.std(finals, ddof=1)) if len(finals) > 1 else 0.0)
        for v in finals:
            individual_xs.append(x)
            individual_ys.append(v)
    plt.bar(xs, means, yerr=stds, capsize=8, alpha=0.5, color=["C0", "C1", "C2"])
    plt.scatter(individual_xs, individual_ys, color="black", zorder=10, s=40, marker="x")
    plt.xticks(xs, conditions)
    plt.ylabel("final best metric (lower is better)")
    plt.title("Final best metric per condition (mean ± std across 3 seeds)")
    plt.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=130)
    plt.close()


def plot_arm_wins(by_cond: dict, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4))
    labels = []
    skippy_vals = []
    bishop_vals = []
    for c in ["bare_faithful", "steelman"]:
        for s in by_cond.get(c, []):
            labels.append(f"{c}_{s['seed']}")
            skippy_vals.append(s.get("skippy_arm_wins", 0))
            bishop_vals.append(s.get("bishop_arm_wins", 0))
    if not labels:
        ax.text(0.5, 0.5, "no PARALLEL_PROPOSER data yet", ha="center", va="center")
        plt.savefig(out_path, dpi=130)
        plt.close()
        return
    x = np.arange(len(labels))
    w = 0.4
    ax.bar(x - w/2, skippy_vals, w, label="Skippy arm", color="C0")
    ax.bar(x + w/2, bishop_vals, w, label="Bishop-via-Skippy arm", color="C2")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("PROMOTE wins")
    ax.set_title("Arm-of-origin for PROMOTEd candidates")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=130)
    plt.close()


def write_writeup_data(out_path: Path) -> dict:
    by_cond = aggregate()
    stats = {c: per_condition_stats(s) for c, s in by_cond.items()}
    pairs = {
        "skippy_vs_bare":   pairwise_comparison(by_cond["skippy_only"], by_cond["bare_faithful"]),
        "skippy_vs_steel":  pairwise_comparison(by_cond["skippy_only"], by_cond["steelman"]),
        "bare_vs_steel":    pairwise_comparison(by_cond["bare_faithful"], by_cond["steelman"]),
    }
    data = {
        "by_condition": stats,
        "pairwise": pairs,
        "raw_summaries": by_cond,
    }
    out_path.write_text(json.dumps(data, indent=2, default=str))
    return data


def main() -> None:
    plot_trajectories(aggregate(), PROJECT_ROOT / "trajectory.png")
    plot_final_with_errorbars(aggregate(), PROJECT_ROOT / "final_per_condition.png")
    plot_arm_wins(aggregate(), PROJECT_ROOT / "arm_wins.png")
    data = write_writeup_data(PROJECT_ROOT / "final_writeup_data.json")
    print(json.dumps(data["by_condition"], indent=2, default=str))


if __name__ == "__main__":
    main()
