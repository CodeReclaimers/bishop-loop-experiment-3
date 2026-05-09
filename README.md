# Bishop-Loop Variant Experiment 3 — JSON Parser

This repo runs the Bishop-loop variant comparison from the experimental
spec: `skippy_only` vs `bare_faithful` vs `steelman` on a JSON parser
optimization problem, three seeds per condition, 90 min wall-clock per run.

## Layout

- `phase/target/json_parser.py` — editable surface (deliberately slow, ~18-25× slower than `json.loads`)
- `phase/target/_baseline_naive.py` — frozen copy of the starting parser; restored at the start of every run
- `phase/reference/json_reference.py` — `json.loads` wrapper used as the correctness oracle
- `phase/corpus/inputs.jsonl` — 200-case fixed corpus (60 shallow, 40 deep, 40 wide, 30 edge, 30 malformed); hash pinned in the manifest
- `phase/bench/manifest.toml` — benchstone manifest
- `phase/bench_runner.py` — subprocess entry point; runs correctness or performance per the benchstone JSON-over-files protocol
- `phase/run_experiment.py` — top-level driver for the 9 (condition × seed) sweep
- `phase/analyze_results.py` — aggregator + plotting
- `phase/build_writeup.py` — turns the aggregation into `final_writeup.md`
- `bishop_loop/` — the loop driver module
- `bishop_loop/BENCHSTONE_NOTES.md` — running notes on benchstone usage

## Running

```bash
# venv is already created at .venv (Python 3.12 + benchstone + scipy/matplotlib)
.venv/bin/python phase/run_experiment.py            # full 9-run sweep, 90 min each
.venv/bin/python phase/run_experiment.py --conditions skippy_only --budget-seconds 240   # smoke
.venv/bin/python phase/analyze_results.py           # aggregate after sweep
.venv/bin/python phase/build_writeup.py             # render final_writeup.md
```

## Models

- Skippy = `qwen3-coder:30b` (Ollama, ~22 GB VRAM)
- Bishop = `qwen2.5-coder:1.5b` (Ollama, ~3 GB VRAM)
- Both kept loaded simultaneously (no swap latency on alternating calls)

## Hardening

- `phase/target/json_parser.py` is the only file the loop edits. Other files
  in `phase/` are read but not written.
- The bench_runner statically rejects candidates that `import json` (the
  standard library `json` module would short-circuit the optimization
  landscape).
- Correctness is checked against the fixed corpus AND 50 randomized cases
  generated fresh with a per-eval seed; the candidate cannot anticipate the
  random inputs.
- Result equality is recursive (lazy / thunked structures fail).
- Mann-Whitney U gate at `promotion_z=1.5`, 3 reps × 3 baseline reps
  (`|z|_max ≈ 2.087`, real headroom over the threshold).
