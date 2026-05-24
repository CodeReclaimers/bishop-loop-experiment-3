# Pre-registration: `skippy_parallel` Control Run

**Committed before any `skippy_parallel`, fresh `skippy_only`, or fresh
`bishop` (bare_faithful) data exists.** The point is to lock in the
analysis plan before the data so the eventual report can't be accused
of post-hoc cut-hunting — the same failure mode the report itself
critiques.

## Why this run

The report's headline comparison (`bare_faithful` / `steelman` vs
`skippy_only`, p=0.001) confounds two variables: model diversity (does
Bishop contribute directional signal?) and search budget (best-of-2
beats best-of-1 almost mechanically). The missing control is
`skippy_parallel`: two independent Skippy draws per iteration, promote
the better. It isolates search budget so that `bishop` vs
`skippy_parallel` measures the *marginal* value of directing one arm
with Bishop's idea over taking a second free draw.

## Conditions (frozen at launch)

All three conditions use **SEARCH/REPLACE in every arm** (brief §0.3):

1. **`skippy_only`** — best-of-1. One Skippy SR draw per iteration.
2. **`skippy_parallel`** — best-of-2. Two independent Skippy SR draws
   (seed offsets 1 and 7919, both at temperature 0.7), promote the
   better. *This is the control the week is buying.*
3. **`bishop`** (= `bare_faithful` in the codebase) — best-of-2. Arm A:
   Skippy SR. Arm B: Bishop 1.5B emits a 2–3 sentence idea, Skippy then
   produces SR blocks implementing it.

Identical harness for all three: same PROMOTE gate
(`promotion_z=1.5`, 3 baseline reps × 3 candidate reps), same correctness
oracle, same 200-input corpus + 50 random cases per eval, same warm-up,
same subprocess timeouts, same `json`-import static guard, same VRAM
watchdog.

## Seed allocation

| Condition | Seeds | Range |
|---|---|---|
| `skippy_only` | 10 | 5001–5010 |
| `skippy_parallel` | 30 | 5101–5130 |
| `bishop` (bare_faithful) | 30 | 5201–5230 |

Budget: 90 minutes wall-clock per (condition, seed) run, matching the
existing data convention. The new seed range (5xxx) keeps these runs
identifiable as the brief's `skippy_parallel` cohort separate from the
1xxx/2xxx/3xxx/4xxx pilots.

`skippy_only` gets a smaller anchor count because best-of-1 vs
best-of-2 is a known large effect (the existing data show a ~5.3 SD
gap); n=10 is sufficient to anchor the secondary comparison without
sacrificing power on the primary. n=30 on the two main arms is
calibrated to the power-calc dry run (see "Power" below).

## Power

Bootstrap simulation on the variance of the existing n=10
`bare_faithful_4xxx` final-metric distribution (mean=0.01009 s,
SD=0.000571 s), Mann-Whitney U two-sided at α=0.05:

| n per arm | Shift at 80% power | as fraction of the original best-of-2 gap |
|---:|---:|---:|
| 20 | 1.00 SD ≈ 0.57 ms | ~19 % |
| **30** | **0.75 SD ≈ 0.43 ms** | **~14 %** |

The "original best-of-2 gap" is the observed
`bare_faithful_4xxx` − `skippy_only_3xxx` mean gap of 0.003 s ≈ 5.26 SD.
Bishop direction's marginal contribution can only be a fraction of
that gap (the rest is the search-budget effect). At n=30 we have 80%
power to detect Bishop contributions ≥ ~14 % of the original gap. If
the true marginal effect is < ~10 % of the gap, neither n=20 nor n=30
will reach significance — this is pre-registered as the "report the
effect-size estimate, do not over-claim a null" outcome.

## Primary comparison (pre-committed)

**`bishop` (n=20) vs `skippy_parallel` (n=20)** on the final
`best_ever_metric` per run (lower is better; metric is seconds to parse
the 200-input corpus).

- Test: two-sided Mann-Whitney U.
- Significance threshold: **α = 0.05**, fixed in advance.
- Effect size reported alongside p-value: Cliff's δ and the
  Hodges-Lehmann shift estimate with 95% CI.

## Secondary comparisons (also pre-committed)

- **`skippy_parallel` vs `skippy_only`** — confirms the search-budget
  effect is real and large. Same test, same α.
- **`bishop` vs `skippy_only`** — the original, now-contextualized
  comparison. Same test, same α.

No correction for multiple comparisons is applied: the primary is
named, and the two secondaries answer different questions.

## Pre-committed interpretation (brief §0.4)

The report's framing is decided in advance for each outcome of the
primary comparison so the eventual text matches the data, not the
analyst's prior:

- **`bishop` > `skippy_parallel`** (p < α): Bishop direction carries
  signal beyond a second free draw. Architecture claim supported.
- **`bishop` ≈ `skippy_parallel`** (p ≥ α, |Cliff's δ| < 0.20): Bishop
  is redundant with a second free draw. The original effect was search
  budget. The report leads with this as a clean cautionary tale about
  search-budget confounds in multi-agent evaluation. **This is the
  most likely outcome and the report is prepared to lead with it.**
- **`bishop` < `skippy_parallel`** (p < α, opposite sign): constraining
  Skippy to implement a weak 1.5B idea actively degrades the arm
  relative to a free draw. Reported and discussed.

## Out of scope this run

- Bishop capability (1.5B vs 4B) — future work, different variable.
- Format ablations (full-rewrite vs SR) — settled by prior pilot.
- Steelman condition — characterised in prior data; this run does not
  re-run it.

## Logging

Per-iteration in `phase/results/{condition}_{seed}/iteration_log.jsonl`:

- proposal text for every arm,
- PROMOTE/REJECT/NEEDS_MORE_DATA verdict per arm,
- per-arm correctness + perf metrics,
- winning arm + winning metric,
- `arm_similarity` — `difflib.SequenceMatcher.ratio()` over the two
  arms' post-SR normalized source. For `skippy_parallel` this is the
  *reference distribution* for the similarity diagnostic (brief §3).

Full proposals saved under `proposals/`; promoted post-SR sources
saved under `diffs/`.

## Frozen harness

- Commit hash: **`02adabe1`** ("Phase 0 for skippy_parallel control run:
  condition + SR-everywhere + VRAM watchdog"). All sweep runs execute
  against this exact harness; the commit is reachable from `main` at
  pre-registration time. Any harness change discovered to be needed
  mid-sweep is documented as an amendment, never as a silent edit.
- Models: Skippy = `qwen3-coder:30b`, Bishop = `qwen2.5-coder:1.5b`
  (Ollama).
- Quantization: whatever Ollama serves by default for those tags on
  this machine. Recorded in `summary.json` indirectly via
  `total_tokens` / `gen_seconds` ratios.
- VRAM watchdog: `scripts/vram_watchdog.sh` at `*/15 * * * *`.

## Stopping rule

No mid-run peeking. All 50 runs complete before any statistical test
is computed. Crashed runs are re-run with the same seed only if the
failure was infrastructure-side (Ollama outage, watchdog-detected CPU
fallback, OOM-kill); model-driven crashes inside a run are not retried
— the run's `iterations_completed` and `best_ever_metric` stand.
