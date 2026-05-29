"""Pre-registered analysis for the skippy_parallel control run.

Reads the 5xxx-seed final best_ever_metric distributions and runs the
three comparisons committed in PREREGISTER.md:

  Primary:   bishop (bare_faithful, n=30) vs skippy_parallel (n=30)
  Secondary: skippy_parallel vs skippy_only
  Secondary: bishop vs skippy_only

Test: two-sided Mann-Whitney U, alpha=0.05.
Effect sizes: Cliff's delta and the Hodges-Lehmann shift estimate with a
95% bootstrap CI.

Metric is seconds to parse the 200-input corpus; LOWER IS BETTER. The
pre-registration phrases the primary as "bishop > skippy_parallel"
meaning bishop is *better* (lower metric). We report direction
explicitly so the sign is unambiguous.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.stats import mannwhitneyu

RESULTS = Path(__file__).resolve().parent / "results"

CONDITIONS = {
    "skippy_only": range(5001, 5011),
    "skippy_parallel": range(5101, 5131),
    "bare_faithful": range(5201, 5231),  # "bishop" in the paper
}


def load_finals(condition: str, seeds) -> np.ndarray:
    out = []
    for s in seeds:
        sj = RESULTS / f"{condition}_{s}" / "summary.json"
        j = json.loads(sj.read_text())
        out.append(float(j["best_ever_metric"]))
    return np.array(out)


def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    """Cliff's delta for a vs b. Positive => a tends to be LARGER than b.

    Since lower metric is better, a positive delta for (X, Y) means X is
    the *slower* (worse) condition.
    """
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return (gt - lt) / (len(a) * len(b))


def hodges_lehmann(a: np.ndarray, b: np.ndarray) -> float:
    """Median of all pairwise differences a_i - b_j."""
    diffs = np.subtract.outer(a, b).ravel()
    return float(np.median(diffs))


def hl_bootstrap_ci(a: np.ndarray, b: np.ndarray, n_boot: int = 10000,
                    seed: int = 20260529) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    na, nb = len(a), len(b)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        sa = rng.choice(a, na, replace=True)
        sb = rng.choice(b, nb, replace=True)
        boots[i] = np.median(np.subtract.outer(sa, sb).ravel())
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(lo), float(hi)


def describe(name: str, x: np.ndarray) -> None:
    print(f"  {name:<16} n={len(x):>2}  mean={x.mean():.6f}  median={np.median(x):.6f}  "
          f"sd={x.std(ddof=1):.6f}  min={x.min():.6f}  max={x.max():.6f}")


def compare(label: str, name_a: str, a: np.ndarray, name_b: str, b: np.ndarray,
            alpha: float = 0.05) -> None:
    print(f"\n{'='*72}\n{label}\n{'='*72}")
    describe(name_a, a)
    describe(name_b, b)

    U, p = mannwhitneyu(a, b, alternative="two-sided")
    delta = cliffs_delta(a, b)           # +: a slower (worse) than b
    hl = hodges_lehmann(a, b)            # a - b (seconds); +: a slower
    lo, hi = hl_bootstrap_ci(a, b)

    # Direction in plain language (lower metric = faster = better).
    if hl < 0:
        better, worse = name_a, name_b
    else:
        better, worse = name_b, name_a
    sig = "SIGNIFICANT" if p < alpha else "not significant"

    print(f"\n  Mann-Whitney U = {U:.1f},  p = {p:.4g}  ({sig} at alpha={alpha})")
    print(f"  Cliff's delta (sign: + means '{name_a}' slower) = {delta:+.3f}")
    print(f"  Hodges-Lehmann shift ({name_a} - {name_b}) = {hl*1000:+.4f} ms"
          f"  [95% CI {lo*1000:+.4f}, {hi*1000:+.4f} ms]")
    mag = abs(delta)
    mag_label = ("negligible" if mag < 0.147 else "small" if mag < 0.33
                 else "medium" if mag < 0.474 else "large")
    print(f"  |Cliff's delta| = {mag:.3f} ({mag_label} effect)")
    if p < alpha:
        print(f"  => {better} is significantly FASTER than {worse}.")
    else:
        print(f"  => no significant difference (point estimate favors {better}).")


def main() -> None:
    data = {c: load_finals(c, seeds) for c, seeds in CONDITIONS.items()}

    print("Final best_ever_metric (seconds to parse 200-input corpus; lower=better)")
    print("Per-condition distributions:")
    for c in ("skippy_only", "skippy_parallel", "bare_faithful"):
        describe(c, data[c])

    # PRIMARY
    compare("PRIMARY: bishop (bare_faithful) vs skippy_parallel",
            "bare_faithful", data["bare_faithful"],
            "skippy_parallel", data["skippy_parallel"])

    # SECONDARY 1
    compare("SECONDARY 1: skippy_parallel vs skippy_only",
            "skippy_parallel", data["skippy_parallel"],
            "skippy_only", data["skippy_only"])

    # SECONDARY 2
    compare("SECONDARY 2: bishop (bare_faithful) vs skippy_only",
            "bare_faithful", data["bare_faithful"],
            "skippy_only", data["skippy_only"])


if __name__ == "__main__":
    main()
