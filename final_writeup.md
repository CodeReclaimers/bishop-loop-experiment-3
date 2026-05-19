# Bishop-Loop Variant Experiment — JSON Parser Optimization

## TL;DR

**Headline:** at n=10 seeds per condition, **bare_faithful** (1.72× speedup over baseline) and **steelman** (1.64×) both clearly beat **skippy_only** (1.40×). The two PARALLEL_PROPOSER conditions are statistically indistinguishable from each other on the final metric (0.0101s vs 0.0105s, std ≈ 0.0006 each). The Bishop-arm-win rate is **higher under bare-faithful** (60%) than under steelman (35%) — the opposite of what the engagement-step hypothesis predicts. Unlike earlier pilots, the bishop-derived arm is now genuinely distinct from the skippy arm (median similarity bare_faithful=0.10, steelman=0.07; ≈ 0% of iterations have ratio ≥ 0.8). The PARALLEL_PROPOSER arms are actually competing approaches, not Skippy regenerating the same code twice. Initial baseline was 0.0175s.

The detailed pairwise comparison and qualitative analysis appear below.

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
| skippy_only_3001 | 340 | 3 | 0.0165 | 0.0205 | 5404.0 | 3 | 0 |
| skippy_only_3002 | 343 | 4 | 0.0143 | 0.0198 | 5411.4 | 4 | 0 |
| skippy_only_3003 | 305 | 3 | 0.0142 | 0.0173 | 5419.2 | 3 | 0 |
| skippy_only_3004 | 314 | 2 | 0.0146 | 0.0173 | 5405.1 | 2 | 0 |
| skippy_only_3005 | 275 | 2 | 0.0141 | 0.0174 | 5409.4 | 2 | 0 |
| skippy_only_3006 | 311 | 1 | 0.0145 | 0.0174 | 5414.9 | 1 | 0 |
| skippy_only_3007 | 280 | 5 | 0.0103 | 0.0175 | 5403.2 | 5 | 0 |
| skippy_only_3008 | 282 | 3 | 0.0108 | 0.0174 | 5403.6 | 3 | 0 |
| skippy_only_3009 | 307 | 2 | 0.0107 | 0.0172 | 5412.8 | 2 | 0 |
| skippy_only_3010 | 276 | 2 | 0.0109 | 0.0174 | 5418.8 | 2 | 0 |
| **skippy_only mean ± std** | 303 | 2.7 | 0.0131 ± 0.0022 | — | — | 27 | 0 |
| bare_faithful_3001 | 180 | 4 | 0.0107 | 0.0175 | 5426.7 | 1 | 3 |
| bare_faithful_3002 | 194 | 5 | 0.0099 | 0.0174 | 5425.9 | 1 | 4 |
| bare_faithful_3003 | 195 | 4 | 0.0108 | 0.0180 | 5404.4 | 3 | 1 |
| bare_faithful_3004 | 209 | 4 | 0.0099 | 0.0171 | 5400.9 | 1 | 3 |
| bare_faithful_3005 | 224 | 2 | 0.0103 | 0.0170 | 5408.5 | 1 | 1 |
| bare_faithful_3006 | 204 | 5 | 0.0101 | 0.0173 | 5400.5 | 3 | 2 |
| bare_faithful_3007 | 222 | 3 | 0.0102 | 0.0173 | 5418.2 | 2 | 1 |
| bare_faithful_3008 | 195 | 3 | 0.0104 | 0.0173 | 5400.0 | 2 | 1 |
| bare_faithful_3009 | 218 | 7 | 0.0088 | 0.0171 | 5405.1 | 1 | 6 |
| bare_faithful_3010 | 166 | 5 | 0.0103 | 0.0180 | 5435.0 | 2 | 3 |
| **bare_faithful mean ± std** | 201 | 4.2 | 0.0101 ± 0.0006 | — | — | 17 | 25 |
| steelman_3001 | 210 | 6 | 0.0108 | 0.0178 | 5412.2 | 3 | 3 |
| steelman_3002 | 236 | 4 | 0.0102 | 0.0170 | 5405.4 | 3 | 1 |
| steelman_3003 | 240 | 2 | 0.0109 | 0.0171 | 5402.9 | 1 | 1 |
| steelman_3004 | 232 | 4 | 0.0103 | 0.0173 | 5415.7 | 1 | 3 |
| steelman_3005 | 247 | 3 | 0.0101 | 0.0172 | 5400.8 | 2 | 1 |
| steelman_3006 | 230 | 2 | 0.0106 | 0.0172 | 5415.3 | 2 | 0 |
| steelman_3007 | 221 | 3 | 0.0102 | 0.0169 | 5408.3 | 2 | 1 |
| steelman_3008 | 230 | 3 | 0.0106 | 0.0173 | 5401.5 | 3 | 0 |
| steelman_3009 | 206 | 3 | 0.0106 | 0.0174 | 5414.0 | 3 | 0 |
| steelman_3010 | 242 | 4 | 0.0105 | 0.0169 | 5405.5 | 2 | 2 |
| **steelman mean ± std** | 229 | 3.4 | 0.0105 ± 0.0003 | — | — | 22 | 12 |

## Cross-condition comparison

See `trajectory.png`, `final_per_condition.png`, and `arm_wins.png` in the repo root.

## Statistical analysis

Pairwise Mann-Whitney U on the 10-vs-10 final-metric distributions:

- **skippy_vs_bare**: a=0.0131, b=0.0101, Mann-Whitney U=95.0, p=0.001. _()_
- **skippy_vs_steel**: a=0.0131, b=0.0105, Mann-Whitney U=90.0, p=0.003. _()_
- **bare_vs_steel**: a=0.0101, b=0.0105, Mann-Whitney U=29.0, p=0.121. _()_

At n=10 per condition the skippy-vs-bare and skippy-vs-steel comparisons are
clearly significant; the bare-vs-steel difference is not. The standard deviations
within each PARALLEL_PROPOSER condition (~0.0006s) are an order of magnitude smaller
than the gap between PARALLEL_PROPOSER and skippy_only, so the two-arm effect dominates
the engagement-step effect at this sample size.

## Qualitative analysis: steelman in action

### Example: steelman_3001 iter 1

**Bishop idea:** Replace the redundant `out = dict(out)` call in `_parse_object` with a direct assignment into the existing dictionary, so each key‑value pair is added without recreating the dict. This eliminates repeated allocations and memory churn during object construction, speeding up parsing while preserving correctness.

**Skippy critique:** The suggestion to replace `out = dict(out)` with direct assignment would break the existing logic because the current code already assigns to `out[key] = value` after the dict reconstruction. The redundant `dict(out)` call doesn't affect the correctness of the assignment but rather creates unnecessary intermediate dictionaries. Simply removing it without adjusting the assignment logic would cause 

**Skippy steelman:** The steelman is to recognize that the redundant `dict(out)` call is indeed unnecessary and can be removed, but the key insight is that we should not be rebuilding the dictionary at all during parsing. Instead, we should directly assign to the existing dictionary object, which is already the correct approach, and the suggestion should be interpreted as eliminating the unnecessary dict reconstructio

**Outcome:** PROMOTE — candidate metric 0.0149 vs baseline 0.0178

### Example: steelman_3001 iter 19

**Bishop idea:** Replace the list `_WS_CHARS` with a set so that checking whether a character is whitespace is O(1) instead of O(k) for each character in the string. This will make `_skip_ws` loop faster because each iteration uses constant‑time membership checks. The rest of the parser can remain unchanged, preserving correctness.

**Skippy critique:** The suggestion to replace `_WS_CHARS` with a set would indeed improve lookup performance, but it fails to consider that the current implementation uses lists for other character sets like `_DIGIT_CHARS` which are also accessed via membership checks. Additionally, the suggestion doesn't address the fact that `_skip_ws` is called repeatedly and could benefit from a more optimized approach like using

**Skippy steelman:** The steelman is to replace all list-based character membership checks with set or frozenset lookups, not just whitespace characters. This ensures consistent O(1) performance across all character set operations while maintaining the existing parsing logic. The change should also consider using `str.isspace()` for whitespace handling as it's highly optimized in CPython.

**Outcome:** PROMOTE — candidate metric 0.0127 vs baseline 0.0149

### Example: steelman_3001 iter 25

**Bishop idea:** Replace the character‑by‑character loop in `_skip_ws` with a single call to `text.find` that looks for the next non‑whitespace character, using the C‑level implementation instead of the Python loop. This eliminates the per‑character Python overhead while still advancing `pos` to the first non‑space character, keeping the parsing logic correct.

**Skippy critique:** The suggestion to replace the character-by-character loop with `text.find` is flawed because `text.find` would need to search the entire string from the current position for any whitespace character, which is inefficient and doesn't handle the case where there are no more whitespace characters (i.e., it would return -1 or continue searching past the end of the string). Additionally, it doesn't pre

**Skippy steelman:** The steelman version would use `text.find` to locate the first non-whitespace character, but it should handle the case where no such character exists (i.e., end of string) by returning the current position or raising an appropriate error, ensuring that `pos` is correctly advanced to the next non-whitespace character while maintaining performance.

**Outcome:** PROMOTE — candidate metric 0.0110 vs baseline 0.0114

### Example: steelman_3002 iter 4

**Bishop idea:** Replace the regex‑based `_skip_ws` implementation with a manual loop that advances the index while `ord(text[pos]) < 0x20`, since all whitespace characters have ordinals below 0x20 and this avoids the overhead of a regex match. This change keeps correctness because it still skips only whitespace and is faster due to the low‑overhead arithmetic and loop.

**Skippy critique:** The suggestion fails to account for the fact that JSON whitespace includes characters beyond those with ordinals below 0x20, specifically U+0009 (tab), U+000A (line feed), U+000D (carriage return), and U+0020 (space). Using `ord(text[pos]) < 0x20` would incorrectly skip non-whitespace characters like 'A' or 'z' and fail to skip valid whitespace like tab or space. Additionally, it ignores that the 

**Skippy steelman:** The steelman version should replace the regex with a manual loop that checks for the specific whitespace characters defined in the JSON standard (space, tab, line feed, carriage return) rather than relying on ord < 0x20. This maintains correctness while avoiding regex overhead, and can be implemented efficiently by checking against a set of valid whitespace characters.

**Outcome:** PROMOTE — candidate metric 0.0103 vs baseline 0.0133

### Example: steelman_3003 iter 3

**Bishop idea:** Replace the _skip_ws function with a simple while‑loop that advances pos while text[pos] is in _WS_CHARS, eliminating the regex call and using the pre‑computed frozenset for constant‑time look‑ups. This removes the overhead of compiling and matching a regex each time, making the whitespace‑skipping step faster while preserving correct token boundaries.

**Skippy critique:** The suggestion to replace the regex with a while-loop using a frozenset would break the whitespace skipping behavior because the current regex `r"[ \t\n\r]*"` advances past *zero or more* whitespace characters, but a simple loop would only advance past *one* whitespace character at a time. This would cause incorrect parsing of multiple consecutive whitespace characters and could lead to parsing fa

**Skippy steelman:** The steelman version of the suggestion is to replace the regex-based `_skip_ws` with an optimized while-loop that advances `pos` as long as `text[pos]` is in `_WS_CHARS`, ensuring that all consecutive whitespace characters are skipped in one pass, while still using the precomputed frozenset for O(1) lookup. This preserves the performance benefits of avoiding regex overhead while maintaining correc

**Outcome:** PROMOTE — candidate metric 0.0109 vs baseline 0.0142


## Post-hoc finding: arms are now genuinely distinct (SEARCH/REPLACE mode)

The original 3-seed sweep showed bare_faithful and steelman PARALLEL_PROPOSER
arms producing near-identical code (median similarity 0.99). The cause was the
full-file-rewrite paradigm: when Skippy was given a free hand to rewrite the
file in response to Bishop's idea, he regenerated his own approach with tiny
variations. The "Bishop arm" was effectively a second Skippy sample.

A series of pilots (documented in `bishop_loop/BENCHSTONE_NOTES.md` and
`phase/results/{bare_faithful,steelman}_2001.*` snapshots) iterated through:
- Full-file rewrite with full-corpus warm-up (memoization gaming surfaced).
- Full-file rewrite with single-input warm-up (placeholder-string bug surfaced).
- Unified diff via GNU patch (97% apply-failure rate — LLMs can't count hunk lines).
- Unified diff via `git apply --recount` (94% apply-failure rate — Skippy hallucinates source content).
- **SEARCH/REPLACE blocks (aider-style).** Skippy quotes exact source text in a SEARCH block
  and provides the replacement; the patcher does literal string substitution. No line
  counting, no context fuzz, robust to hallucination because the SEARCH must match
  the source exactly to apply.

The 10-seed sweep uses SEARCH/REPLACE mode for both PARALLEL_PROPOSER conditions.
Result: arm-to-arm similarity collapsed from median 0.99 to median **~0.07-0.10**,
with 0% of iterations having ratio ≥ 0.8. The Bishop-derived arm is now genuinely
the baseline source + a small targeted edit, while the Skippy arm is a full
rewrite — they are competing approaches, not duplicates.

The headline result above is computed against this corrected experimental design.

## Control: is the high bishop-arm rate from the format change or the model swap?

The pilot pipeline conflated two changes: Bishop was swapped from `qwen2.5-coder:1.5b`
to `nemotron-3-nano:4b`, AND the application format was swapped from full-file rewrite
to SEARCH/REPLACE. A 3-seed control sweep (seeds 4001-4003) re-runs bare_faithful +
steelman with `qwen2.5-coder:1.5b` Bishop under SEARCH/REPLACE mode, isolating the
two effects.

| condition | nemotron-4B + SR (n=10) | qwen-1.5B + SR (n=3) |
|---|---|---|
| bare_faithful best | 0.0101 ± 0.0006 | 0.0104 ± 0.0005 |
| bare_faithful bishop-arm wins | 60% (25/42) | 50% (7/14) |
| steelman best | 0.0105 ± 0.0003 | 0.0103 ± 0.0003 |
| steelman bishop-arm wins | 35% (12/34) | 53% (8/15) |

Final metrics are statistically identical across both Bishop models. Bare_faithful's
bishop-win rate is within noise (50% vs 60%, n=3 control). Steelman's is actually
*higher* with the smaller Bishop (53% vs 35%), the opposite of what capability scaling
would predict (though n=3 is too small to call a real effect).

**Conclusion:** the SEARCH/REPLACE format change was the load-bearing fix, not the
Bishop-model swap. The original 22% bishop-win rate (qwen-1.5B + full-rewrite) reflected
the same-arms-degeneracy confound, not a Bishop-capability ceiling. Given a format that
actually applies Bishop's edit to the source, even a 1.5B Bishop produces ideas that
compete with Skippy's full-rewrite arm.

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
