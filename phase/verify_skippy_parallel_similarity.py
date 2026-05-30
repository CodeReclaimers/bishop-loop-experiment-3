"""Reproduce the §5.4 proposal-block arm-similarity numbers for the 5xxx sweep.

Verification companion to RESULTS_skippy_parallel.md §4 and paper §5.4 item 3.

Methodology note (important): in the 5xxx sweep every arm emits aider-style
SEARCH/REPLACE, so a single response contains *several* fenced blocks (one per
hunk). We therefore concatenate ALL fenced blocks per response before scoring
-- comparing each arm's full proposed change -- rather than only the first
block. (phase/arm_similarity.py extracts just the first block, which was
representative for the 3xxx full-file-rewrite responses where one block was the
entire file, but would capture only one hunk here.) Per-line normalization
(comment/blank stripping) is reused verbatim from arm_similarity.py.

Metric: difflib.SequenceMatcher(None, s, b, autojunk=False).ratio() on the
concatenated, normalized fenced blocks of each arm's raw response.

Arms compared per condition:
  skippy_parallel (5101-5130): skippy_a  vs  skippy_b
  bare_faithful   (5201-5230): skippy    vs  bishop_bare   ("bishop" in paper)

Parallelized across cores (difflib on full SR rewrites is O(n*m) per pair).
Run from the phase/ directory:  python3 verify_skippy_parallel_similarity.py
"""
from __future__ import annotations

import difflib
import os
import re
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from arm_similarity import _normalize_code

RESULTS = Path(__file__).resolve().parent / "results"

CONDITIONS = {
    "skippy_parallel": (range(5101, 5131), "skippy_a", "skippy_b"),
    "bare_faithful":   (range(5201, 5231), "skippy", "bishop_bare"),  # "bishop"
}

_BLOCK_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def all_blocks(text: str) -> str | None:
    blocks = _BLOCK_RE.findall(text)
    return "\n".join(blocks) if blocks else None


def _collect_pairs(cond: str, seeds, arm_a: str, arm_b: str):
    pairs = []
    for s in seeds:
        proposals = RESULTS / f"{cond}_{s}" / "proposals"
        if not proposals.exists():
            continue
        for pa in sorted(proposals.glob(f"iter_*_{arm_a}_response.txt")):
            it = re.match(r"iter_(\d+)_", pa.name).group(1)
            pb = proposals / f"iter_{it}_{arm_b}_response.txt"
            if pb.exists():
                pairs.append((str(pa), str(pb)))
    return pairs


def _ratio(pair) -> float | None:
    fa, fb = pair
    ca = all_blocks(Path(fa).read_text())
    cb = all_blocks(Path(fb).read_text())
    if ca is None or cb is None:
        return None
    na, nb = _normalize_code(ca), _normalize_code(cb)
    if not na or not nb:
        return None
    return difflib.SequenceMatcher(None, na, nb, autojunk=False).ratio()


def main() -> None:
    print("Proposal-block arm similarity, 5xxx sweep "
          "(all fenced SR blocks; difflib ratio; 1.0 = identical proposals)\n")
    header = f"{'condition':<16} {'arms':<22} {'n':>6} {'mean':>7} {'median':>7} " \
             f"{'%>=0.95':>8} {'%<=0.30':>8} {'%<=0.10':>8}"
    print(header)
    print("-" * len(header))
    with Pool(min(32, os.cpu_count() or 1)) as pool:
        for cond, (seeds, arm_a, arm_b) in CONDITIONS.items():
            pairs = _collect_pairs(cond, seeds, arm_a, arm_b)
            vals = [v for v in pool.map(_ratio, pairs, chunksize=16) if v is not None]
            r = np.array(vals)
            label = "bishop" if cond == "bare_faithful" else cond
            print(f"{label:<16} {arm_a+' vs '+arm_b:<22} {r.size:>6} "
                  f"{r.mean():>7.3f} {np.median(r):>7.3f} "
                  f"{(r >= 0.95).mean()*100:>7.1f}% "
                  f"{(r <= 0.30).mean()*100:>7.1f}% "
                  f"{(r <= 0.10).mean()*100:>7.1f}%", flush=True)


if __name__ == "__main__":
    main()
