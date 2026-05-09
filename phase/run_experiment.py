"""Driver for the full 9 (condition × seed) sweep.

Usage:
  # All 9 runs:
  python phase/run_experiment.py

  # Subset:
  python phase/run_experiment.py --conditions skippy_only --seeds 1001

  # Smoke (very short budget for testing wiring):
  python phase/run_experiment.py --budget-seconds 60 --max-iterations 1

Conditions are run serially. Each (condition, seed) writes to
`phase/results/{condition}_{seed}/`.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bishop_loop import loop  # noqa: E402

CONDITIONS = ["skippy_only", "bare_faithful", "steelman"]
SEEDS = [1001, 1002, 1003]
DEFAULT_BUDGET_SECONDS = 90 * 60  # 90 minutes per spec §5.4

RESULTS_DIR = PROJECT_ROOT / "phase" / "results"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--conditions", nargs="+", default=CONDITIONS, choices=CONDITIONS)
    p.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
    p.add_argument("--budget-seconds", type=float, default=DEFAULT_BUDGET_SECONDS)
    p.add_argument("--skip-existing", action="store_true",
                   help="Skip combinations whose summary.json already exists")
    args = p.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    summaries = []
    for condition in args.conditions:
        for seed in args.seeds:
            run_dir = RESULTS_DIR / f"{condition}_{seed}"
            if args.skip_existing and (run_dir / "summary.json").exists():
                print(f"[skip] {condition}/{seed}: summary.json already exists", flush=True)
                summaries.append(json.loads((run_dir / "summary.json").read_text()))
                continue
            print(f"\n=== {condition}/{seed} ===", flush=True)
            t0 = time.monotonic()
            try:
                summary = loop.run(
                    condition=condition,
                    seed=seed,
                    budget_seconds=args.budget_seconds,
                    out_dir=run_dir,
                )
            except Exception as e:
                import traceback
                print(f"[error] {condition}/{seed} crashed: {e}\n{traceback.format_exc()}", flush=True)
                summary = {
                    "condition": condition,
                    "seed": seed,
                    "early_stop_reason": "crash",
                    "error": str(e),
                    "wall_clock_elapsed_s": time.monotonic() - t0,
                }
                (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
            summaries.append(summary)
            print(f"=== {condition}/{seed} done in {time.monotonic() - t0:.1f}s ===\n", flush=True)

    total_elapsed = time.monotonic() - started
    aggregate = {
        "total_wall_clock_s": total_elapsed,
        "summaries": summaries,
    }
    (RESULTS_DIR / "all_runs.json").write_text(json.dumps(aggregate, indent=2, default=str))
    print(f"\nAll done. Total wall-clock: {total_elapsed/60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
