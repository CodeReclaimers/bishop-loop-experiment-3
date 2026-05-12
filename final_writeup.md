# Bishop-Loop Variant Experiment — JSON Parser Optimization

## TL;DR

**Headline:** bare-faithful and steelman both beat skippy_only on the metric — means 1.67× and 1.50× over baseline vs skippy_only's 1.28× — **but a retrospective text-similarity analysis shows the gain is not from Bishop's contribution.** In 95% of bare_faithful iterations and 98% of steelman iterations, Skippy's two arms produced near-identical code (difflib ratio ≥ 0.8). The PARALLEL_PROPOSER advantage is mostly a best-of-2-Skippy-samples ensemble effect, not the engagement-step hypothesis the spec set out to test. When Skippy *does* produce a distinct implementation of Bishop's literal idea (ratio < 0.65), it fails correctness 100% of the time — Bishop=qwen2.5-coder:1.5b ideas are too thin to survive faithful implementation. With n=3, none of the pairwise speedup differences are statistically significant (Mann-Whitney p > 0.10 for all pairs), and the similarity finding suggests more seeds with this setup will not resolve the headline question. See "Post-hoc finding" below for the full breakdown.

The detailed pairwise comparison and qualitative analysis appear below. With 3 seeds per
condition, this experiment is **underpowered** for any but very large effects;
report-as-evidence-not-as-conclusion applies.

## Recovery events during the sweep

Two distinct failure modes were caught mid-sweep and patched. Documented for honesty
and because they reveal load-bearing hardening details the spec didn't fully anticipate.

1. **Infinite-loop candidate hung the entire loop** (~20 hr lost). A candidate's
   `_skip_ws` used `re.compile(r'\s*').match(text, pos)` — the zero-width match returns
   a Match object whose `end()` equals `pos`, so the while-loop never advances. The
   bishop-loop's pre-flight correctness check was in-process and had no timeout, so the
   whole sweep stalled silently. **Fix:** route correctness through the subprocess path
   with `subprocess.run(timeout=30)`. Lost run preserved as
   `phase/results/bare_faithful_1001.partial-2026-05-09/`.

2. **Memoization spec-gaming.** A candidate (bare_faithful/1002 iter 131) added a
   module-level `_parse_cache = {}` dict and memoized by input text. The bench_runner's
   warm-up loop parsed all 200 corpus inputs (intended to stabilize one-time imports);
   the timed pass got 200 cache hits in 43 microseconds for a ~400× apparent speedup.
   **Fix:** warm-up calls `parse(inputs[0])` once, not the full corpus, leaving ≤1
   cache entry; timed pass has 199 cache misses out of 200, neutralizing the exploit.
   Gamed run preserved as `phase/results/bare_faithful_1002.gamed-2026-05-10/`.

**Asymmetry note:** the 3 skippy_only runs and bare_faithful_1001 used the old bench_runner
(full-corpus warm-up). All other runs used the patched bench_runner. Spot-check: none of
those four "clean" runs grew a parse cache or any module-level dict in their PROMOTEd
candidates, so the asymmetry contributes at most ~5-10% timing overhead (one-time
module setup no longer absorbed by warm-up), small relative to the 1.2-1.8× speedups
reported.

## Per-condition results

| condition_seed | iters | promotes | best metric | initial metric | wall_s | skippy wins | bishop wins |
|----|----|----|----|----|----|----|----|
| skippy_only_1001 | 315 | 1 | 0.0141 | 0.0168 | 5404.4 | 1 | 0 |
| skippy_only_1002 | 313 | 3 | 0.0139 | 0.0171 | 5409.4 | 3 | 0 |
| skippy_only_1003 | 312 | 4 | 0.0122 | 0.0171 | 5410.1 | 4 | 0 |
| **skippy_only mean ± std** | 313 | 2.7 | 0.0134 ± 0.0011 | — | — | 8 | 0 |
| bare_faithful_1001 | 145 | 3 | 0.0094 | 0.0169 | 5408.6 | 2 | 1 |
| bare_faithful_1002 | 157 | 2 | 0.0106 | 0.0173 | 5432.2 | 2 | 0 |
| bare_faithful_1003 | 170 | 4 | 0.0108 | 0.0170 | 5422.4 | 3 | 1 |
| **bare_faithful mean ± std** | 157 | 3.0 | 0.0103 ± 0.0007 | — | — | 7 | 2 |
| steelman_1001 | 142 | 4 | 0.0131 | 0.0168 | 5411.6 | 2 | 2 |
| steelman_1002 | 155 | 1 | 0.0106 | 0.0173 | 5424.5 | 1 | 0 |
| steelman_1003 | 146 | 2 | 0.0108 | 0.0171 | 5409.4 | 1 | 1 |
| **steelman mean ± std** | 148 | 2.3 | 0.0115 ± 0.0014 | — | — | 4 | 3 |

## Cross-condition comparison

See `trajectory.png`, `final_per_condition.png`, and `arm_wins.png` in the repo root.

## Statistical analysis

Pairwise Mann-Whitney U on the 3-vs-3 final-metric distributions:

- **skippy_vs_bare**: a=0.0134, b=0.0103, Mann-Whitney U=9.0, p=0.100. _(underpowered with n=3 per side)_
- **skippy_vs_steel**: a=0.0134, b=0.0115, Mann-Whitney U=8.0, p=0.200. _(underpowered with n=3 per side)_
- **bare_vs_steel**: a=0.0103, b=0.0115, Mann-Whitney U=2.0, p=0.400. _(underpowered with n=3 per side)_

**Power note:** With n=3 per side, the smallest non-degenerate U statistic that can yield
p<0.10 in a two-sided test is around p≈0.10 (rare ordering); detecting medium effects
requires substantially more seeds. Treat these p-values as descriptive, not as significance.

## Qualitative analysis: steelman in action

### Example: steelman_1001 iter 1

**Bishop idea:** To speed up parsing JSON, we can use a more efficient string concatenation mechanism by avoiding unnecessary calls to `str.join`. We can do this by maintaining a buffer and only appending characters when they are needed. This change will reduce the overhead of string concatenation and improve performance, especially for large inputs.

**Skippy critique:** The suggestion to "avoid unnecessary calls to `str.join`" is unworkable because it
doesn't identify where `str.join` is actually used in the code — the current
implementation uses string concatenation (`out = out + c`) but not `str.join`.
Additionally, the suggestion doesn't address the real bottlenecks like
repeated dict/list rebuilding, per-character scanning, or redundant whitespace
skipping. I

**Skippy steelman:** The steelman version of the idea is to reduce the overhead of string
concatenation by using a list as a buffer and only joining at the end,
especially for large strings. This avoids repeated allocations and copies
during string building in `_parse_string`, and can also be applied to
building object keys and array elements where possible, reducing the number
of intermediate string objects created d

**Outcome:** PROMOTE — candidate metric 0.0137 vs baseline 0.0168

### Example: steelman_1001 iter 8

**Bishop idea:** To speed up the JSON parser, we can replace string concatenation with list concatenation in `_parse_string` where applicable. This reduces the overhead of repeated allocations and copies during string building, especially for large strings. The idea is to use a list as a buffer that only gets joined at the end, avoiding unnecessary intermediate string objects created during parsing.

**Skippy critique:** The suggestion to "replace string concatenation with list concatenation" in `_parse_string` is unworkable because it misidentifies the performance bottleneck. The current implementation already uses a list buffer (`buffer = []`) and only calls `"".join(buffer)` at the end, which is the correct and optimal approach. The suggestion incorrectly implies that the existing code uses inefficient string c

**Skippy steelman:** The steelman version of the idea is to ensure that all string building operations — especially in `_parse_string`, but also in places like object and array construction — use list buffers to avoid repeated allocations and copies. This should be applied consistently to reduce intermediate string objects and improve performance for large inputs, while preserving correctness and maintaining the exist

**Outcome:** PROMOTE — candidate metric 0.0131 vs baseline 0.0133

### Example: steelman_1003 iter 1

**Bishop idea:** To optimize the `parse` function for speed, we can replace the explicit concatenation and rebuilding of collections with a more efficient approach. Specifically, we can use a list to store the values and rebuild the dictionary only when necessary. This reduces the overhead of string concatenation in each iteration of the loop.

**Skippy critique:** The suggestion to "use a list to store the values and rebuild the dictionary only when necessary" is problematic because it misidentifies the core performance bottleneck. The current code already rebuilds collections on every iteration (e.g., `out = dict(out); out[key] = value`), which is inefficient, but simply switching to list storage without addressing the fundamental issues like redundant whi

**Skippy steelman:** The steelman version should focus on reducing Python-level overhead by using efficient string slicing and built-in functions where possible, and by minimizing redundant work. Specifically, we can improve number parsing with `float()` and `int()` directly, avoid redundant whitespace skipping, and reduce unnecessary string concatenations by using `io.StringIO` or list-based building with `join()` wh

**Outcome:** PROMOTE — candidate metric 0.0130 vs baseline 0.0171


## Post-hoc finding: the bare-faithful and steelman arms are largely degenerate

After the sweep, a retrospective text-similarity analysis (`phase/arm_similarity.py`)
computed `difflib.SequenceMatcher.ratio()` between the Skippy arm's and the
Bishop-derived arm's code in each iteration of the PARALLEL_PROPOSER conditions.

| similarity bucket | bare_faithful n | bishop arm correct% | bishop arm wins | steelman n | bishop correct% | bishop wins |
|---|---|---|---|---|---|---|
| <0.65 (distinct) | 13 | 0% | 0 | 5 | 0% | 0 |
| 0.65-0.85 | 18 | 28% | 0 | 2 | 0% | 0 |
| 0.85-0.95 | 50 | 50% | 1 | 67 | 69% | 2 |
| 0.95-1.00 (near-identical) | 388 | 88% | 1 | 368 | 92% | 1 |

Median similarity is 0.991 for bare_faithful and 0.993 for steelman; 95% / 98% of
iterations have similarity ≥ 0.8. **In the vast majority of iterations, the
Bishop-derived arm is essentially a second Skippy proposal with cosmetic
variations**, not a faithful implementation of Bishop's idea.

Two patterns visible in the breakdown:

1. **When Skippy *does* produce a distinct implementation of Bishop's idea
   (similarity <0.65), it almost always fails correctness** (0% pass on
   bare_faithful, 0% on steelman). Bishop=qwen2.5-coder:1.5b ideas, taken
   literally, produce code Skippy can't make correct in one rewrite.

2. **When Skippy "implements" Bishop's idea by regenerating his own approach
   (similarity ≥ 0.95), correctness is fine** (88-92% pass) **but the
   condition is no longer testing Bishop's contribution** — it's a
   best-of-2-Skippy-samples ensemble.

**Implication for the headline result.** The 1.67× bare_faithful and 1.50×
steelman mean speedups, both better than the 1.27× skippy_only baseline, are
likely *not* explained by Bishop's idea distribution adding signal. They are
better explained by running two Skippy samples per iteration and taking the
best. The Bishop-arm-wins-43%-of-promotes statistic in steelman, which looked
encouraging in the TL;DR, also lands inside this near-identical bucket: of the
3 Bishop-arm wins in steelman, only 2 are in the <0.95 similarity range (and
those are 0.867 and 0.877 — still highly overlapping). The "engagement step"
isn't engaging with a meaningfully different idea distribution.

**This was anticipated as a spec confound** (§10 point 6: "Skippy may have
implemented a Bishop idea but improved it anyway despite instructions").
What's new is the magnitude: median 0.99 similarity is the strong form of
that confound, not the marginal-degradation form the spec described.

## Confounds and limitations

- **Small sample (3 seeds).** Means and stds are computed on n=3.
- **Ollama seed unreproducibility.** The same seed produces different responses across calls
  to qwen3-coder:30b; runs are different from each other but not bit-reproducible.
- **Same-family Bishop and Skippy.** Bishop=qwen2.5-coder:1.5b, Skippy=qwen3-coder:30b;
  diff-family Bishop is a deliberately separate question (see prior writeups).
- **Bare-faithful constraint leakage.** Skippy may have improved on Bishop's idea even when
  asked not to; this is hard to detect post hoc and would attenuate the difference between
  bare-faithful and steelman.
- **Per-iteration time differs across conditions.** Steelman iterations take longer than
  bare-faithful (extra critique-and-steelman generation) which take longer than skippy-only.
  At fixed wall-clock, lower-overhead conditions get more iterations.
- **Banned `import json`.** A trivial `json.loads`-wrapper would short-circuit the
  optimization landscape; the harness statically rejects candidate files that import the
  `json` standard library module. This forces the optimization to remain in the
  algorithmic / structural cleverness regime the spec intended.

## What benchstone showed and didn't

# Benchstone integration notes

Running list of benchstone usage observations and gaps encountered while
building the bishop-loop experiment 3 harness against benchstone v0.1.1
(local install from `/home/alan/benchstone/dist/benchstone-0.1.1-py3-none-any.whl`).

## Design choice: bypass the CLI for the per-iteration evaluator

The bishop-loop's PARALLEL_PROPOSER pattern (bare_faithful, steelman) needs to
evaluate two arms per iteration *against the same baseline*. Each arm:

1. Edits `phase/target/json_parser.py`.
2. Runs the perf benchmark 3 times.
3. Compares to the baseline distribution.
4. Is reverted if it doesn't win.

Doing this through the `bench` CLI requires:

- Either committing each arm before `bench run` (since the harness refuses
  dirty trees by default), then `git reset --hard HEAD~1` if it loses. Two
  arms means two commits-and-reverts per iteration — a lot of git churn.
- Or running with `--allow-dirty`, but then both arms' rows accumulate at the
  same SHA and the gate sees them mixed (the README documents this:
  `--allow-dirty` rows are not excluded from gates).
- Or per-arm git worktrees with separate `BENCHSTONE_HOME` per worktree.
  Doable but heavy for a 90-minute experiment.

We instead use `benchstone.stats.mann_whitney_z` directly as the gate, run
the bench runner subprocess via the same JSON-over-files protocol the harness
would use, and keep our own JSONL log of per-iteration history. This keeps
the gate semantics identical to the CLI while skipping the git workflow that
fights the loop pattern.

The trade-off: we don't get benchstone's append-only SQLite store. We do get
per-(condition, seed) JSONL logs that capture more bishop-loop-specific
detail than the store schema would have anyway (proposal text, critiques,
arm winners), so this is a reasonable substitution.

## Gaps observed

- **No documented pattern for "two candidates at the same SHA, gated
  independently."** The natural way to do this with the CLI is per-arm
  worktrees, which the README mentions as a one-off for `bench baseline
  establish --at-sha`, not as a per-iteration pattern.
- **`--allow-dirty` rows blend with clean rows in the gate.** Documented in
  `README.md > Limits worth being explicit about`, but the practical
  implication for two-arm autoloops is that you cannot use `--allow-dirty`
  for arm comparison.
- **No CLI command to run a benchmark and immediately gate against an
  in-memory baseline distribution.** The shape of `bench run` + `bench
  evaluate` assumes (baseline at sha A) → (candidate at sha B) where
  baseline is in the store. Compatible only with the commit-per-arm pattern.
- **No "gate two candidate distributions against each other" primitive.** A
  PARALLEL_PROPOSER autoloop wants "given runs from arm A and arm B at the
  same SHA, which one is better?" — that's not something `bench evaluate`
  supports today. The library has `mann_whitney_z`; calling it directly is
  a one-liner workaround.

## Ollama seed reproducibility caveat

`POST /api/generate` with the same `seed` returns *different* responses
across two calls for both `qwen2.5-coder:1.5b` and `qwen3-coder:30b` on
Ollama 0.20.4. This is unrelated to benchstone but documented here so the
experimental setup is reproducible only at the run level (different seeds
produce different runs), not at the bit level. Per the spec §5.6, we
proceed with this caveat.

## Misc

- Manifest loader requires `repetitions >= 2` for non-correctness benches
  (warns at load if `< 2`); we use 3 which fits.
- `gate_policy = "mann_whitney"` requires explicit `promotion_z` to silence
  a load-time warning. We set `promotion_z = 1.5` per the spec's §3.6
  recommendation.

## Recovery: warm-up loop populated candidate's memoization cache

`bare_faithful/1002` reported `best_ever_metric = 4.35e-05` — ~400× faster than
the baseline. The candidate (iter 131) added a module-level dict
`_parse_cache = {}` and memoized by input text. The bench_runner's warm-up loop
parsed all 200 corpus inputs to "stabilize one-time imports" — populating the
cache. The timed pass then got 200 cache hits in 43 microseconds, no real
parsing. Recursive equality still passed because the cached values were
structurally correct: the exploit was in *timing*, not correctness.

**Fix:** warm-up calls `parse(inputs[0])` once instead of iterating the corpus.
This still amortizes one-time module setup (regex compilation etc.) on the
first call but limits the cache to ≤1 entry, neutralizing the 200× exploit
(timed pass would have 199 cache misses out of 200).

Result preserved as `phase/results/bare_faithful_1002.gamed-2026-05-10/` so
the writeup can quote the gaming pattern. Runs after this point use the fixed
bench_runner; runs before (3 skippy_only + bare_faithful_1001) used the old
bench_runner with full-corpus warm-up. Asymmetry impact: ~5-10% overhead per
candidate (the new code includes any one-time setup costs the old absorbed),
small relative to the ~1.2-1.8× speedups observed.

**Generalizable lesson:** a warm-up that touches the full corpus is an
attractive nuisance for memoizing candidates. Either skip warm-up entirely,
warm with a single representative input, or run warm-up in a separate
subprocess so module-level state is reset before timing.

## Recovery: subprocess timeout vs in-process correctness check

During the actual sweep, `bare_faithful/1001` hung at iter ~178 (~87 min in)
because a candidate `_skip_ws` was implemented as:

```python
_WS_RE = re.compile(r'\s*')
def _skip_ws(text, pos):
    while pos < len(text):
        m = _WS_RE.match(text, pos)
        if not m: break
        pos = m.end()
    return pos
```

`r'\s*'` matches a zero-width string at any position, so `m` is always truthy
and `m.end() == pos`, looping forever. The candidate's `parse()` was called
in-process by the bishop-loop's pre-flight correctness check, which had no
timeout guard. The whole sweep stalled silently for ~20 hours of wall-clock
before being killed and resumed.

The bench_runner's `WHOLE_CORRECTNESS_TIMEOUT_S = 60.0` only checks between
test cases — it doesn't preempt a single hung `parse()` call. The fix is to
run correctness via the subprocess path with a hard `subprocess.run(timeout=30)`
which Popen-kills the child process. This costs ~70 ms per check vs the
in-process version, but bench_runner round-trips dominate that anyway.

**Generalizable lesson for autoloops:** if your candidate is untrusted code
(LLM-generated), every entry point that loads/runs it must be either out-of-process
with a hard timeout, or wrapped in `signal.alarm` (single-threaded only) or a
watchdog thread that can `os._exit`. An in-process call with no preemption is
a session-ending failure mode, not a recoverable one.


## Suggested follow-ups

The retrospective similarity analysis changes the priority order. More seeds with the
current setup will tighten the mean estimates but won't resolve the headline question
(does the engagement step matter?) because the engagement step is barely engaging.

Priority order for next experiments:

- **More-capable Bishop.** The 1.5B model produces ideas that, when faithfully
  implemented, fail correctness 100% of the time (n=13 bare_faithful, n=5 steelman).
  A 4-7B Bishop (nemotron-3-nano:4b, qwen2.5-coder:7b) could produce ideas Skippy is
  able to implement correctly without falling back to his own approach. This is the
  single highest-value change.
- **Force diff-style application instead of full file rewrite.** Instead of asking
  Skippy to rewrite the whole file given Bishop's idea, ask Skippy to produce a *minimal
  diff* targeting only the lines Bishop named. Skippy's tendency to regenerate the
  whole file from scratch (which is where his own approach takes over) is suppressed.
- **Stronger anti-collapse prompting.** "Reject" responses that don't substantively
  change the input file. Could be enforced via the same similarity ratio: if Skippy's
  output has >0.95 ratio to the current file *and* >0.95 to the parallel Skippy arm,
  reject as "did not implement the suggestion." This re-runs Bishop's idea generation
  to surface a different idea.
- **Then, with the above fixes, repeat with more seeds (≥10 per condition).** Once the
  bishop-arm is genuinely different from the skippy arm, more seeds become useful.
- **Two-round steelman** is downstream of all of the above — it only matters if the
  one-round steelman shows signal.

---

_Generated by `phase/build_writeup.py` from `final_writeup_data.json`._
