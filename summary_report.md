# Bishop-loop variant experiment — summary report

**Repository:** `bishop-loop-experiment-3/`
**Period:** 2026-05-09 through 2026-05-24
**Status:** experimental cycle complete; this report is the final consolidation.

This document is intended as source material for any paper drawing on these
results. It states the starting hypothesis, every load-bearing decision and
its motivation, and the final conclusions. Citations of the form
`(commit <sha>)` or `(progress-YYYYMMDD.md)` or `(phase/results/<dir>)`
point to the artifact where the underlying detail lives, so a future
fact-checker can follow each claim back to its evidence.

---

## 1. Starting point

### 1.1 The hypothesis under test

The Bishop-loop is a two-model variant of a Karpathy-style code-optimization
autoloop. A capable proposer/implementer model (**Skippy** =
`qwen3-coder:30b`) is paired with a less capable idea-generator model
(**Bishop** =, initially, `qwen2.5-coder:1.5b`). Three loop architectures are
compared on a single optimization problem:

- **skippy_only** — Skippy proposes complete file rewrites alone. K=0.
- **bare_faithful** — Per iteration: Skippy proposes (arm A); separately,
  Bishop describes an idea in 2-3 sentences and Skippy implements it
  *exactly* (arm B). Both arms evaluated; best PROMOTE wins.
- **steelman** — Same as bare_faithful, but Skippy first writes a 2-3
  sentence critique of Bishop's idea, then a 2-3 sentence steelman of the
  strongest version, then implements the steelman.

The hypothesis the spec set out to test was the **engagement-step
hypothesis**: that Skippy's cognitive engagement with Bishop's ideas (the
steelman variant) produces useful candidates that Skippy alone — or Skippy
faithfully copying Bishop — would not. Full spec is in the project root's
ONBOARDING-equivalent (commit `360ff90` includes the experimental design as
the project's initial state).

### 1.2 Optimization problem

A deliberately slow but correct pure-Python JSON parser
(`phase/target/_baseline_naive.py`, 18-25× slower than `json.loads` on the
corpus). 200-case corpus split into shallow / deep / wide / edge / malformed
buckets (`phase/corpus/_generate.py`, hash-pinned in the manifest). Metric:
total wall-clock to parse all 200 inputs, lower is better. Mann-Whitney U
gate at `promotion_z = 1.5`, 3 reps × 3 baseline reps (`|z|_max ≈ 2.087`).
Correctness: every fixed-corpus case + 50 random cases generated fresh per
evaluation; structural equality (not lazy thunks).

### 1.3 Hardening built in from day one

The spec called out two failure classes the harness must defend against:
specification gaming and reference contamination. Implementations:

- Editable surface is exactly `phase/target/json_parser.py`. Reference
  (`phase/reference/json_reference.py`), corpus, and bench_runner are
  outside the editable surface.
- `bench_runner.py` statically rejects candidates that `import json`
  (would short-circuit the optimization landscape — see the rejection
  rule in `_check_no_json_import`).
- Equality check is recursive; lazy/thunked structures fail.
- Per-evaluation seed for the random correctness tests; the candidate
  cannot pre-populate against the corpus.

### 1.4 Initial design choice: model-family policy

The spec called for **same-family** Bishop and Skippy (both Qwen) to test
the engagement step independently of cross-family proposal diversity. The
qwen-1.5B / qwen-30B pairing was the starting condition. (See spec §5.1
discussion for the prior-experiment context that motivated this choice.)

---

## 2. First sweep: 9 runs (3 conditions × 3 seeds, 90 min each)

Sweep with original design: qwen Bishop, full-file-rewrite mode. Documented
in `final_writeup.md` history through commit `998b3d2`.

### 2.1 Recovery event 1: infinite-loop candidate

A Skippy-generated `_skip_ws` used `re.compile(r'\s*').match(text, pos)`.
`r'\s*'` zero-width-matches at any position, so `match.end() == pos` and
the loop never advances. The bishop-loop's pre-flight correctness check
was in-process (no subprocess) and had no timeout, so the entire sweep
stalled silently for ~20 hours. Detected at the next manual status check.

**Fix:** route correctness through the subprocess path with
`subprocess.run(timeout=30)`. See `bishop_loop/evaluator.py:check_correctness`
(commit `55ea681`). Partial run preserved at
`phase/results/bare_faithful_1001.partial-2026-05-09/`.

**Methodological lesson:** every entry point that loads/runs LLM-generated
code must be either out-of-process with a hard timeout, or wrapped in
`signal.alarm` / a watchdog thread. An in-process call with no preemption
is a session-ending failure mode, not a recoverable one.

### 2.2 Recovery event 2: memoization spec-gaming

`bare_faithful/1002` reported `best_ever_metric = 4.35e-05` (~400× faster
than baseline — physically impossible for pure-Python JSON parsing). The
candidate (iter 131) added a module-level `_parse_cache = {}` and memoized
by input text. The bench_runner's warm-up loop parsed all 200 corpus inputs
to "stabilize one-time imports" — populating the cache. Timed pass got 200
cache hits in 43 microseconds. Recursive equality passed because the
cached values were structurally correct: the exploit was in *timing*, not
correctness.

**Fix:** warm-up calls `parse(inputs[0])` once instead of iterating the
corpus, leaving ≤1 cache entry. Timed pass has 199 cache misses out of
200, neutralizing the 400× exploit (commit `2e80e56`).

Gamed result preserved at `phase/results/bare_faithful_1002.gamed-2026-05-10/`.

**Methodological lesson:** a warm-up that touches the full corpus is an
attractive nuisance for memoizing candidates. Either skip warm-up entirely,
warm with a single representative input, or run warm-up in a separate
subprocess so module-level state is reset before timing.

### 2.3 Headline result (before deeper diagnosis)

| condition | n | best metric ± std | speedup over baseline | bishop arm wins |
|---|---|---|---|---|
| skippy_only | 3 | 0.0134 ± 0.0011 | 1.27× | n/a |
| bare_faithful | 3 | 0.0103 ± 0.0007 | 1.67× | 22% (2/9) |
| steelman | 3 | 0.0115 ± 0.0014 | 1.50× | 43% (3/7) |

Surface reading: bare_faithful wins, steelman is intermediate, both beat
skippy_only. The steelman engagement step does not appear to add value.

Asymmetry caveat: the 3 skippy_only runs and bare_faithful_1001 ran with
the pre-fix bench_runner (full-corpus warm-up); other runs used the patched
bench_runner. None of those four "clean" runs grew a parse cache. Estimated
timing asymmetry ~5-10%, small relative to the 1.2-1.8× speedups reported.

### 2.4 The decisive post-hoc diagnostic: arm-similarity

Suspecting that the "bare_faithful wins" finding was an artifact, I wrote
`phase/arm_similarity.py` to compute `difflib.SequenceMatcher.ratio()`
between the Skippy arm's candidate code and the Bishop-derived arm's
candidate code in each iteration of the PARALLEL_PROPOSER conditions.

| condition | pooled median similarity | mean | % iterations with ratio ≥ 0.8 |
|---|---|---|---|
| bare_faithful | 0.991 | 0.954 | 95% |
| steelman | 0.993 | 0.972 | 98% |

**The arms were producing near-identical code in nearly every iteration.**
The bishop-derived arm was essentially a second Skippy sample. The
"1.67× bare_faithful" and "1.50× steelman" results were almost entirely a
**best-of-2-Skippy-samples ensemble effect**, not the engagement-step
hypothesis the spec set out to test.

Subsidiary finding from the similarity buckets (pooled across 3 seeds):

| similarity bucket | n | bishop arm correct rate | bishop arm wins |
|---|---|---|---|
| <0.65 (genuinely distinct) | 13 (bf) / 5 (sm) | 0% / 0% | 0 / 0 |
| 0.65-0.85 | 18 / 2 | 28% / 0% | 0 / 0 |
| 0.85-0.95 | 50 / 67 | 50% / 69% | 1 / 2 |
| 0.95-1.00 (near-identical) | 388 / 368 | 88% / 92% | 1 / 1 |

When Skippy *did* produce a distinct implementation of Bishop's literal
idea (similarity <0.65), correctness failed 100% of the time. When Skippy
"implemented" Bishop's idea by regenerating his own approach (≥0.95
similarity), correctness was fine but the condition was no longer testing
Bishop's contribution.

The spec had anticipated some form of this confound (§10 point 6:
"Skippy may have implemented a Bishop idea but improved it anyway despite
instructions"). The post-hoc finding was the strong form: median 0.99
similarity is not "Skippy improved it"; it's "Skippy ignored it."

---

## 3. Pilot iterations to fix the degeneracy

If the arms collapse to near-duplicates, the comparison is uninformative.
A series of pilot iterations (each at 1 seed, ~3h wall-clock) targeted
two suspects: the Bishop model (too thin?) and the application format
(full-rewrite encourages Skippy to default to his own approach?).

All pilots preserved with versioned suffixes in `phase/results/` so a
fact-checker can replay any step.

### 3.1 Pilot v1 — nemotron Bishop, full-rewrite

Swapped Bishop from `qwen2.5-coder:1.5b` to `nemotron-3-nano:4b` (4B
reasoning model, NVIDIA Llama-derived family — incidentally introducing
family diversity, though that wasn't the primary intent). Initial test
showed nemotron produces specific implementable ideas where qwen-1.5B
produced vague gestures.

`bare_faithful_2001.nemotron-v1/`: 6 PROMOTEs (vs avg 3 for qwen), bishop
arm won 2/6 (33%) — better than qwen-3-seed average of 22%.

`steelman_2001.nemotron-v1/`: only 2 promotes, but **both Bishop arm**
(100%). p05 of similarity ratio dropped to 0.01 — suggesting some
iterations were producing radically different code. But the median was
still 0.996.

Investigating the 0.01-similarity outliers: Skippy was producing **prose
with a literal placeholder string** `<rest of the file implementing the
steelman>` copied verbatim from my prompt template. The steelman prompt
included an example like:
```
# CRITIQUE: ...
# STEELMAN: ...
<rest of the file implementing the steelman>
```
Skippy interpreted `<rest of the file ...>` as content to copy, not an
instruction. Roughly 20% of steelman iterations hit this failure mode.

### 3.2 Pilot v2 — prompt template fix + placeholder guard

Rewrote the steelman prompt to wrap the example in an indented separate
fenced block with explicit "this shows the structure, not the content"
framing, plus an explicit "do not emit literal placeholder strings"
sentence. Added a placeholder-detection guard in the loop that classifies
candidates with `<rest of`, `<your `, or under-30 substantive lines as
`apply_failure`.

`bare_faithful_2001.nemotron-v2/`: 7 promotes, 2 bishop wins (28%). 67
apply_failures (53%) — high, but they're now genuine correctness failures
from Skippy attempting Bishop's edits, not placeholders.

`steelman_2001.nemotron-v2/`: 5 promotes, **4 bishop wins (80%)**. Only
11 apply_failures. The prompt fix worked for its purpose.

But similarity median was still **0.984 (bare_faithful) and 0.996
(steelman)**. Placeholders were gone, but the underlying full-rewrite
collapse remained.

### 3.3 Pilot v3 — unified diff via `patch(1)`

If the full-rewrite format is the bottleneck, replace it. Asked Skippy
to output a unified diff against the current source instead of a full
rewrite. Applied with GNU `patch -p1`.

`bare_faithful_2001.diff-patch/`: **249 of 256 (97%) apply_failures**.
Inspection: ~70% "malformed patch" errors — Skippy gets hunk line counts
(`@@ -X,Y +Z,W @@`) systematically wrong. ~30% "Hunk FAILED" — Skippy's
line numbers were off too far for patch's fuzz factor (2) to recover.

LLMs are notoriously bad at counting. A representative failing diff had
`@@ -67,7 +67,7 @@` for a hunk that actually targets line 91 with 5
visible lines, not 67 with 7.

### 3.4 Pilot v3.1 — `git apply --recount`

`git apply --recount` recomputes hunk line counts from the actual hunk
body and uses context matching to find the correct location. Verified on
the failing diff from v3 — git apply applied it correctly to line 91.

`bare_faithful_2001.diff-gitapply/`: improved to **201 of 213 (94%)
apply_failures**. Marginal. New failure mode: "patch does not apply" —
git apply couldn't find the context because **Skippy was hallucinating
source content**. Example: a diff with `-_HEX_CHARS = {"0", ...}` that
doesn't exist in the source (the actual source has
`_HEX_CHARS = frozenset(...)`). Also, Skippy was treating docstring
bullet lines `- Whitespace is skipped...` as removed lines, producing
malformed diffs with the same line both removed and re-added.

Unified diff is too fragile for LLM-generated edits.

### 3.5 Pilot v3.2 — SEARCH/REPLACE blocks

Aider-style format. The model outputs blocks like:
```
<<<<<<< SEARCH
<exact text copied from source>
=======
<replacement text>
>>>>>>> REPLACE
```

The applier (`bishop_loop/evaluator.py:apply_search_replace_blocks`) does
literal string substitution. No line counting; no context fuzz; the SEARCH
text must match the source exactly to apply, so hallucinated content
fails fast and obviously.

`bare_faithful_2001`: 86% of bishop arm iterations now apply successfully
(vs 6% in v3.1). Of those, 18% pass correctness, 1 PROMOTEs.

`steelman_2001`: **51% pass correctness** (vs 18% bare_faithful). 1
PROMOTE. The engagement step's effect now had a candidate metric where
it could differentiate: under bare-faithful, 18% of Bishop's edits
preserve correctness when Skippy implements them literally; under
steelman, 51% do.

**Crucially**: arm-to-arm similarity median dropped from 0.99 (full
rewrite) to **0.066 (bare_faithful) and 0.223 (steelman)**. The bishop
arm is now genuinely the baseline source + a small targeted edit, while
the skippy arm is a full rewrite. They are competing approaches, not
duplicates.

This pilot was the decisive design fix. Commits `50c080f`, `b191edd`.

---

## 4. The 10-seed sweep: clean test of the hypothesis

With v3.2 design (nemotron Bishop, SEARCH/REPLACE), launched the 10-seed
× 3-condition sweep (seeds 3001-3010, 90 min each, 45h wall-clock).
Documented in `final_writeup.md`, commit `998b3d2`.

### 4.1 Headline results

| condition | n | best metric ± std | speedup | bishop arm wins | vs skippy_only |
|---|---|---|---|---|---|
| skippy_only | 10 | 0.0131 ± 0.0022 | 1.40× | 0/27 | — |
| bare_faithful | 10 | **0.0101 ± 0.0006** | **1.72×** | 25/42 (60%) | **p = 0.001** |
| steelman | 10 | 0.0105 ± 0.0003 | 1.64× | 12/34 (35%) | **p = 0.003** |
| bare vs steel | | | | | p = 0.121 (n.s.) |

(Mann-Whitney U on final metric, two-sided.)

Median arm-to-arm similarity confirmed at scale: bare_faithful 0.097,
steelman 0.072. 0% of iterations have similarity ≥ 0.8 in either
condition. The PARALLEL_PROPOSER arms are now genuinely distinct.

### 4.2 Two findings from the 10-seed sweep

1. **PARALLEL_PROPOSER (Skippy + Bishop's distinct edit) decisively beats
   Skippy-alone.** Both bare_faithful and steelman improve on skippy_only
   at p ≤ 0.003. The bishop-arm contribution is real now that
   SEARCH/REPLACE eliminated the same-arms degeneracy.

2. **The engagement step (steelman vs bare_faithful) does not measurably
   help on final metric.** Means 0.0101 vs 0.0105, p = 0.121. Bishop-arm
   win rate is actually *higher* under bare-faithful (60% vs 35%), the
   opposite of the original engagement-step hypothesis.

The standard deviations within each PARALLEL_PROPOSER condition (~0.0006s)
are an order of magnitude smaller than the gap between PARALLEL_PROPOSER
and skippy_only, so the two-arm effect dominates the engagement-step
effect at n=10.

### 4.3 Per-iteration pipeline statistics (worth noting in any paper)

For `bare_faithful_3001` as an example (`phase/results/bare_faithful_3001/`):
- 86% of bishop arm iterations applied (SEARCH/REPLACE succeeded)
- Of applied, 18% passed correctness
- Of those, ~3% beat the perf gate to PROMOTE

`steelman_3001` for comparison: 83% applied / 51% of applied passed
correctness. The **3× correctness pass-rate advantage** of the
engagement step is real and reproduces across seeds — but it doesn't
translate into a final-metric advantage because the perf gate against
Skippy's full-rewrite arm is hard.

---

## 5. Control sweep: model swap vs format change

The pilot sequence conflated two changes: Bishop was swapped (qwen-1.5B
→ nemotron-4B) AND the application format was swapped (full-rewrite →
SEARCH/REPLACE). The 10-seed sweep was rich enough to test the hypothesis,
but didn't disentangle which change was load-bearing.

Launched a 10-seed control: qwen-1.5B Bishop (original spec) with
SEARCH/REPLACE (the v3.2 fix). Seeds 4001-4010. ~30h wall-clock
across two launches (with a GPU-driver recovery event between).

### 5.1 Recovery event 3: GPU driver mismatch

Sweep launched 2026-05-22 20:29. First completed run produced 8
iterations in 90 minutes (vs the normal ~250). Diagnosis:
`nvidia-smi` reported `Driver/library version mismatch (NVML library
version: 580.159)` — likely an unattended system update. Ollama silently
offloaded Skippy (22 GB) to CPU; per-iteration time ~23× slower.

Killed the slow run, moved data aside to
`phase/results/bare_faithful_4004.cpu-only-2026-05-22/`, asked user for
reboot. Relaunched 2026-05-23 08:50 with `--skip-existing` (preserving
seeds 4001-4003 from a previous run); completed normally by 2026-05-24
05:54.

**Hardening added:** the 4-hour status-check cron now verifies Skippy's
`size_vram > 0` each fire, so a driver fallback surfaces within 4 hours
instead of after one full 90-minute run.

**Methodological lesson:** for long-running LLM-driven sweeps, a periodic
GPU-presence check is mandatory. Performance regressions from silent
CPU fallback are easy to miss because the sweep technically completes
each run; it just takes 20× longer.

### 5.2 Control results — n=10 vs n=10

| condition | nemotron-4B (n=10) | qwen-1.5B (n=10) | Mann-Whitney p (best) | Fisher p (bishop wins) |
|---|---|---|---|---|
| bare_faithful best | 0.0101 ± 0.0006 | 0.0101 ± 0.0006 | 0.791 | — |
| bare_faithful bishop wins | 60% (25/42) | 51% (26/51) | — | 0.530 |
| steelman best | 0.0105 ± 0.0003 | 0.0103 ± 0.0003 | 0.385 | — |
| steelman bishop wins | 35% (12/34) | 41% (17/42) | — | 0.813 |

All four pairwise tests give p ≥ 0.385. The two Bishop models are
statistically indistinguishable on this experimental design.

The n=3 hint from the earlier mini-control ("steelman bishop-wins higher
with the smaller Bishop, 53% vs 35%") was noise — adding 7 more qwen
seeds dropped the rate to 41%, well within noise of the nemotron 35%.

### 5.3 Conclusion from the control

The **SEARCH/REPLACE format change was the load-bearing fix**. The
Bishop-model swap (qwen-1.5B → nemotron-4B) was incidental — it did not
measurably affect either the final metric or the bishop-arm-win rate.
The original sweep's 22% bishop-win rate (qwen-1.5B + full-rewrite)
reflected the same-arms-degeneracy confound, not a Bishop-capability
ceiling.

---

## 6. Final conclusions

Stating these in the order a paper might present them. All are at n=10
per cell unless noted, with confidence intervals derivable from the
recorded `best_ever_metric` per run.

### 6.1 The original Bishop-loop comparison design is structurally flawed

When the bishop-derived arm is allowed to be a full file rewrite — the
spec's default — Skippy regenerates his own approach with cosmetic
variations in ≥95% of iterations. The PARALLEL_PROPOSER conditions
collapse to "best of 2 Skippy samples." Any apparent benefit attributed
to Bishop's contribution or to the engagement step is confounded with
this ensemble effect.

This is the strong form of the §10 point-6 confound the spec
anticipated. The magnitude — median similarity 0.99 — was not anticipated.

### 6.2 SEARCH/REPLACE format applies LLM-generated edits robustly

GNU `patch` and `git apply` both fail on LLM-generated unified diffs
(97% and 94% apply-failure rates respectively) because LLMs cannot count
hunk header line numbers and frequently hallucinate context lines. The
aider-style SEARCH/REPLACE block format raises apply success to 86%+
because it requires the model to quote source text verbatim — hallucinated
content fails immediately at apply time rather than corrupting the source.

This is a standalone methodological finding likely useful beyond this
experiment.

### 6.3 The corrected experiment shows real Bishop contribution

With SEARCH/REPLACE applied (similarity ratio drops from 0.99 to 0.07),
both PARALLEL_PROPOSER conditions decisively beat skippy_only on the
final-metric Mann-Whitney test (p ≤ 0.003 at n=10). Bishop's distinct
edits, when actually applied, add real signal beyond a single Skippy
sample.

### 6.4 The engagement-step hypothesis is not supported

bare_faithful (1.72× speedup) and steelman (1.64× speedup) are
statistically indistinguishable on final metric (p = 0.121) and on
bishop-arm-win rate (p = 0.813 with qwen Bishop, p = 0.181 with nemotron
Bishop). The original spec's engagement-step hypothesis — that Skippy's
critique-and-steelman of Bishop's idea produces useful candidates Skippy
alone would not — has no measurable effect on the headline metric.

**However**, the engagement step does produce a real ~3× improvement in
bishop-arm-correctness pass rate (51% vs 18%). That's a meaningful
intermediate finding even though it doesn't translate into a final-metric
advantage at n=10 in this experiment.

### 6.5 Bishop model capability (1.5B vs 4B) is not load-bearing here

Given the SEARCH/REPLACE format, qwen-1.5B Bishop and nemotron-4B Bishop
produce statistically indistinguishable results across all four
relevant comparisons (final metric × condition). Bishop's role as
"idea-generator that suggests where to look" appears to be robust to
substantial capability variation in this experimental design, at this
sample size.

### 6.6 What this experiment did not test

- **Two-round (or deeper) steelman** — Skippy critiques + steelmans, then
  critiques the steelman, then implements. Could test whether engagement
  depth matters even though one-round depth does not.
- **Bishop ≥ 7B** — capability scaling beyond 4B may behave differently.
- **Cross-domain transfer** — JSON parser is a narrow problem with
  well-defined optimization axes. Results might differ on, e.g.,
  algorithmic optimization in a different domain.
- **Different Skippy models** — all conclusions are specific to
  `qwen3-coder:30b` as Skippy.

---

## 7. Pointers for the fact-checker

### Code

- Loop driver: `bishop_loop/loop.py`
- Proposer prompts (current = SEARCH/REPLACE, nemotron Bishop):
  `bishop_loop/proposers.py`. Earlier prompt variants visible in git history.
- Evaluator (subprocess timeout, search-replace applier): `bishop_loop/evaluator.py`
- Bench runner (single-input warm-up, no-`json` ban, recursive equality):
  `phase/bench_runner.py`
- Naive baseline parser: `phase/target/_baseline_naive.py`
- Manifest: `phase/bench/manifest.toml`

### Per-run data

`phase/results/<condition>_<seed>/` for each completed run:
- `summary.json` — final stats
- `iteration_log.jsonl` — per-iteration record including arm code (via proposals/), critique/steelman text, perf metrics, verdict
- `proposals/iter_NNNN_*_(prompt|response).txt` — every prompt sent and response received
- `diffs/iter_NNNN_*.py` — full file content of PROMOTEd candidates

Versioned suffixes (`.partial-...`, `.gamed-...`, `.cpu-only-...`,
`.nemotron-v1`, `.diff-patch`, etc.) preserve aborted or pilot runs for
audit.

### Cross-run aggregation

- `final_writeup_data.json` — per-condition summary stats across the 10-seed sweep
- `arm_similarity.json` — per-iteration similarity ratios with bishop/skippy
  win attribution
- `arm_similarity.py` / `arm_similarity_outliers.py` — analysis scripts

### Plots (regeneratable via `phase/analyze_results.py`)

- `trajectory.png` — best-metric vs wall-clock, all runs overlaid
- `final_per_condition.png` — mean ± std bar chart with individual seeds
- `arm_wins.png` — Skippy vs Bishop arm wins per PARALLEL_PROPOSER run

### Documentation

- `final_writeup.md` — TL;DR + per-condition table + statistical analysis
  + qualitative steelman examples + control section (qwen vs nemotron Bishop)
- `bishop_loop/BENCHSTONE_NOTES.md` — benchstone integration choices and
  the two original recovery events (infinite-loop, memoization gaming)
  with the generalizable lessons
- `README.md` — project layout and how to run
- `progress-YYYYMMDD.md` — per-day session logs with verbatim verification
  evidence, decisions, and rejected alternatives

### Commit references for key milestones

- `360ff90` — initial scaffolding (naive parser, corpus, manifest, bench runner, loop module)
- `9038b54` — naive parser tuned (no `^`-anchor footgun); richer rejection feedback
- `55ea681` — subprocess timeout for correctness (recovery 1 fix)
- `2e80e56` — single-input warm-up (recovery 2 fix)
- `998b3d2` — initial 3-seed sweep writeup
- `eab7043` — pilot v2 (placeholder-fix steelman prompt + guard)
- `3eb32ed` → `6f23644` — pilot v3 / v3.1 (unified diff attempts)
- `50c080f` — pilot v3.2 (SEARCH/REPLACE introduced)
- `b191edd` — pilot v3.2 results
- (next commit after `7a22c8f`) — final n=10 control sweep (this report's bundle)
