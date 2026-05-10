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
