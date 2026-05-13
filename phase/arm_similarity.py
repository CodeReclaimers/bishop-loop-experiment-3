"""Retrospective check: how similar is the Bishop-derived arm's code to the
Skippy arm's code, per iteration, for the PARALLEL_PROPOSER conditions?

The concern: in `bare_faithful`, Skippy is told to implement Bishop's idea
"exactly, no improvements." If Skippy ignores that and produces code very
similar to what the Skippy arm produced in the same iteration, the two arms
are effectively the same proposal — and the bare_faithful condition is just
running skippy_only with extra steps. This script measures that.

For each iteration of `bare_faithful_*` and `steelman_*`:
  1. Load both arms' raw model responses.
  2. Extract the python code block from each.
  3. Normalize (strip comments, blank lines, leading whitespace) and compute
     difflib.SequenceMatcher.ratio() between the two normalized code strings.
  4. Aggregate and report.

A ratio of 1.0 means the two arms produced identical code; 0.0 means
nothing in common. Real implementations of the same base parser are usually
in the 0.4-0.8 range because they share structural skeletons (function
signatures, control flow, escape tables) even when the parsing strategy
differs.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "phase" / "results"

PARALLEL_CONDITIONS = ["bare_faithful", "steelman"]
SEEDS = [1001, 1002, 1003, 2001]  # 2001 is the nemotron-Bishop pilot


def _extract_python_block(text: str) -> str | None:
    m = re.search(r"```(?:python|py)\s*\n(.*?)```", text, re.DOTALL)
    if m is not None:
        return m.group(1)
    m = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if m is not None:
        return m.group(1)
    return None


def _normalize_code(code: str) -> str:
    """Strip comments, blank lines, leading whitespace differences.

    We want to detect *structurally similar* code, not formatting noise.
    Keep tokens intact so SequenceMatcher operates on code substance.
    """
    out_lines = []
    for ln in code.splitlines():
        # Strip inline comments (rough — doesn't handle # inside strings, fine for our purpose).
        nocomment = re.sub(r"#.*$", "", ln)
        stripped = nocomment.strip()
        if not stripped:
            continue
        out_lines.append(stripped)
    return "\n".join(out_lines)


def _bishop_arm_name(condition: str) -> str:
    return "bishop_bare" if condition == "bare_faithful" else "bishop_steelman"


def analyze_run(condition: str, seed: int) -> dict | None:
    run_dir = RESULTS_DIR / f"{condition}_{seed}"
    proposals = run_dir / "proposals"
    log_path = run_dir / "iteration_log.jsonl"
    if not proposals.exists() or not log_path.exists():
        return None
    bishop_name = _bishop_arm_name(condition)

    # We compare arms on iterations that have both responses available.
    ratios = []
    arm_outcomes = []  # tuples of (ratio, skippy_passed, bishop_passed, winner)
    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        it = d.get("iter")
        if it is None:
            continue
        skippy_resp = proposals / f"iter_{it:04d}_skippy_response.txt"
        bishop_resp = proposals / f"iter_{it:04d}_{bishop_name}_response.txt"
        if not skippy_resp.exists() or not bishop_resp.exists():
            continue
        skippy_code = _extract_python_block(skippy_resp.read_text())
        bishop_code = _extract_python_block(bishop_resp.read_text())
        if skippy_code is None or bishop_code is None:
            continue
        s = _normalize_code(skippy_code)
        b = _normalize_code(bishop_code)
        if not s or not b:
            continue
        ratio = difflib.SequenceMatcher(None, s, b, autojunk=False).ratio()
        ratios.append(ratio)

        # Match up correctness/verdict per arm
        arms = {a["arm"]: a for a in d.get("arms", [])}
        sk = arms.get("skippy") or {}
        bi = arms.get(bishop_name) or {}
        sk_pass = (sk.get("correctness") or {}).get("passed", False)
        bi_pass = (bi.get("correctness") or {}).get("passed", False)
        arm_outcomes.append({
            "iter": it,
            "ratio": ratio,
            "skippy_passed": sk_pass,
            "bishop_passed": bi_pass,
            "winner": d.get("winning_arm"),
        })

    if not ratios:
        return None
    arr = np.array(ratios)
    return {
        "condition": condition,
        "seed": seed,
        "n_iterations_compared": int(arr.size),
        "median_ratio": float(np.median(arr)),
        "mean_ratio": float(np.mean(arr)),
        "frac_gte_0_5": float((arr >= 0.5).mean()),
        "frac_gte_0_7": float((arr >= 0.7).mean()),
        "frac_gte_0_8": float((arr >= 0.8).mean()),
        "frac_gte_0_9": float((arr >= 0.9).mean()),
        "p05": float(np.quantile(arr, 0.05)),
        "p25": float(np.quantile(arr, 0.25)),
        "p50": float(np.quantile(arr, 0.50)),
        "p75": float(np.quantile(arr, 0.75)),
        "p95": float(np.quantile(arr, 0.95)),
        "all_ratios": [float(x) for x in arr],
        "per_iter_outcomes": arm_outcomes,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(PROJECT_ROOT / "arm_similarity.json"))
    args = p.parse_args()

    results = {}
    for cond in PARALLEL_CONDITIONS:
        results[cond] = []
        for seed in SEEDS:
            r = analyze_run(cond, seed)
            if r is not None:
                results[cond].append(r)
                print(
                    f"{cond}_{seed}: n={r['n_iterations_compared']:3d}  "
                    f"median={r['median_ratio']:.3f}  "
                    f"mean={r['mean_ratio']:.3f}  "
                    f">=0.8: {r['frac_gte_0_8']:.0%}  "
                    f">=0.9: {r['frac_gte_0_9']:.0%}  "
                    f"p05-p95: [{r['p05']:.2f}, {r['p95']:.2f}]"
                )

    # Pooled stats per condition
    print()
    print("Pooled by condition:")
    for cond, runs in results.items():
        if not runs:
            continue
        pooled = [r for run in runs for r in run["all_ratios"]]
        arr = np.array(pooled)
        print(
            f"{cond:14s} n={arr.size:4d}  "
            f"median={np.median(arr):.3f}  "
            f"mean={np.mean(arr):.3f}  "
            f">=0.8: {(arr >= 0.8).mean():.0%}  "
            f">=0.9: {(arr >= 0.9).mean():.0%}"
        )
    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
