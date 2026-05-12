"""Slice the similarity data to learn whether the rare "Bishop actually
implemented" iterations produce different outcomes than the high-similarity
"Skippy ignored Bishop" iterations.

If bishop-arm wins are concentrated in low-similarity iterations: the
engagement step actually mattered when it happened, just rarely.
If bishop-arm wins are uniformly distributed across similarities: PROMOTEs
are mostly luck-of-two-samples, not Bishop's contribution.
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((PROJECT_ROOT / "arm_similarity.json").read_text())


def bucket(ratio: float) -> str:
    if ratio >= 0.95:
        return "0.95-1.00 (near-identical)"
    if ratio >= 0.85:
        return "0.85-0.95 (mostly same)"
    if ratio >= 0.65:
        return "0.65-0.85 (substantial overlap)"
    return "<0.65 (distinct)"


for cond in ("bare_faithful", "steelman"):
    print(f"\n=== {cond} ===")
    bishop_arm_name = "bishop_bare" if cond == "bare_faithful" else "bishop_steelman"
    by_bucket = {}
    for run in DATA.get(cond, []):
        for entry in run["per_iter_outcomes"]:
            b = bucket(entry["ratio"])
            by_bucket.setdefault(b, {
                "n": 0, "bishop_win": 0, "skippy_win": 0, "neither_win": 0,
                "skippy_passed_correctness": 0, "bishop_passed_correctness": 0,
            })
            r = by_bucket[b]
            r["n"] += 1
            w = entry.get("winner")
            if w == "skippy": r["skippy_win"] += 1
            elif w == bishop_arm_name: r["bishop_win"] += 1
            else: r["neither_win"] += 1
            if entry["skippy_passed"]: r["skippy_passed_correctness"] += 1
            if entry["bishop_passed"]: r["bishop_passed_correctness"] += 1
    for b in ["<0.65 (distinct)", "0.65-0.85 (substantial overlap)", "0.85-0.95 (mostly same)", "0.95-1.00 (near-identical)"]:
        r = by_bucket.get(b)
        if r is None:
            continue
        n = r["n"]
        print(
            f"  {b:34s} n={n:4d}  "
            f"bishop_win={r['bishop_win']:2d} ({r['bishop_win']/n:.1%})  "
            f"skippy_win={r['skippy_win']:2d} ({r['skippy_win']/n:.1%})  "
            f"neither={r['neither_win']:3d}  "
            f"skippy_correct={r['skippy_passed_correctness']/n:.0%}  "
            f"bishop_correct={r['bishop_passed_correctness']/n:.0%}"
        )

# Pick a few low-similarity, bishop-won iterations to inspect manually
print("\n--- Lowest-similarity Bishop wins (most informative cases) ---")
for cond in ("bare_faithful", "steelman"):
    bishop_arm_name = "bishop_bare" if cond == "bare_faithful" else "bishop_steelman"
    candidates = []
    for run in DATA.get(cond, []):
        for entry in run["per_iter_outcomes"]:
            if entry.get("winner") == bishop_arm_name:
                candidates.append((entry["ratio"], run["seed"], entry["iter"]))
    candidates.sort()
    print(f"\n{cond}: {len(candidates)} bishop wins total. Lowest-similarity ones:")
    for ratio, seed, it in candidates[:5]:
        print(f"  similarity={ratio:.3f}  {cond}_{seed}/iter_{it:04d}")
