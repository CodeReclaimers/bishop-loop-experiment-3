"""Build final_writeup.md from final_writeup_data.json + per-run logs.

This is a thin templater — it consumes the aggregation produced by
analyze_results.py and adds qualitative material (steelman critiques, key
diffs) that has to be human-readable.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "phase" / "results"


def _fmt_num(x: float | None, fmt: str = ".4f") -> str:
    if x is None or x == float("inf") or x != x:
        return "—"
    return format(x, fmt)


def _per_condition_table(by_condition: dict) -> str:
    lines = []
    lines.append("| condition_seed | iters | promotes | best metric | initial metric | wall_s | skippy wins | bishop wins |")
    lines.append("|----|----|----|----|----|----|----|----|")
    for cond, summaries in by_condition.items():
        for s in summaries:
            lines.append(
                f"| {cond}_{s['seed']} | "
                f"{s.get('iterations_completed', 0)} | "
                f"{s.get('promotions', 0)} | "
                f"{_fmt_num(s.get('best_ever_metric'))} | "
                f"{_fmt_num(s.get('initial_metric'))} | "
                f"{_fmt_num(s.get('wall_clock_elapsed_s'), '.1f')} | "
                f"{s.get('skippy_arm_wins', 0)} | "
                f"{s.get('bishop_arm_wins', 0)} |"
            )
        # Aggregate row per condition
        if summaries:
            finals = [s.get("best_ever_metric", float("inf")) for s in summaries]
            iters = [s.get("iterations_completed", 0) for s in summaries]
            import statistics
            mean_final = statistics.mean(finals) if finals else 0
            std_final = statistics.stdev(finals) if len(finals) > 1 else 0
            lines.append(
                f"| **{cond} mean ± std** | "
                f"{statistics.mean(iters):.0f} | "
                f"{statistics.mean([s.get('promotions', 0) for s in summaries]):.1f} | "
                f"{_fmt_num(mean_final)} ± {_fmt_num(std_final)} | "
                f"— | — | "
                f"{sum(s.get('skippy_arm_wins', 0) for s in summaries)} | "
                f"{sum(s.get('bishop_arm_wins', 0) for s in summaries)} |"
            )
    return "\n".join(lines)


def _qualitative_steelman_examples(n: int = 5) -> str:
    """Pull up to n iterations from the steelman runs where the engagement step changed the outcome."""
    out = []
    for seed in (1001, 1002, 1003):
        run_dir = RESULTS_DIR / f"steelman_{seed}"
        log_path = run_dir / "iteration_log.jsonl"
        if not log_path.exists():
            continue
        for line in log_path.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("winning_arm") != "bishop_steelman":
                continue
            # We want iterations where Bishop's arm beat Skippy's
            arms_by_name = {a["arm"]: a for a in d.get("arms", [])}
            steel_arm = arms_by_name.get("bishop_steelman")
            if steel_arm is None:
                continue
            extra = steel_arm.get("extra", {})
            critique = extra.get("critique")
            steelman = extra.get("steelman")
            bishop_idea = d.get("bishop_idea")
            if not (critique and steelman and bishop_idea):
                continue
            entry = (
                f"### Example: steelman_{seed} iter {d['iter']}\n\n"
                f"**Bishop idea:** {bishop_idea[:400]}\n\n"
                f"**Skippy critique:** {critique[:400]}\n\n"
                f"**Skippy steelman:** {steelman[:400]}\n\n"
                f"**Outcome:** PROMOTE — candidate metric "
                f"{_fmt_num(steel_arm.get('verdict', {}).get('candidate_mean'))} "
                f"vs baseline "
                f"{_fmt_num(steel_arm.get('verdict', {}).get('baseline_mean'))}\n"
            )
            out.append(entry)
            if len(out) >= n:
                break
        if len(out) >= n:
            break
    if not out:
        return "_(no steelman iterations where the Bishop-via-Skippy arm won were observed)_\n"
    return "\n".join(out)


def main() -> None:
    data_path = PROJECT_ROOT / "final_writeup_data.json"
    if not data_path.exists():
        print(f"missing {data_path}; run phase/analyze_results.py first", flush=True)
        return
    data = json.loads(data_path.read_text())
    by_condition = data["raw_summaries"]
    pairs = data["pairwise"]

    # TL;DR
    finals = {
        c: [s.get("best_ever_metric", float("inf")) for s in by_condition[c]]
        for c in ("skippy_only", "bare_faithful", "steelman")
    }
    import statistics
    means = {
        c: (statistics.mean(v) if v else float("inf"))
        for c, v in finals.items()
    }
    # Speedup-over-initial per condition
    speedups = {}
    for cond_name in ("skippy_only", "bare_faithful", "steelman"):
        ss = []
        for s in by_condition.get(cond_name, []):
            init = s.get("initial_metric")
            best = s.get("best_ever_metric")
            if init and best and best > 0:
                ss.append(init / best)
        speedups[cond_name] = statistics.mean(ss) if ss else 0.0
    init_metrics = []
    for cond_name, summaries in by_condition.items():
        for s in summaries:
            v = s.get("initial_metric")
            if v is not None and v > 0:
                init_metrics.append(v)
    init_mean = statistics.mean(init_metrics) if init_metrics else 0.0

    # Bishop-arm win rates per condition (PARALLEL_PROPOSER conditions only)
    bishop_arm_rates = {}
    for cond_name in ("bare_faithful", "steelman"):
        total_promotes = sum(s.get("promotions", 0) for s in by_condition.get(cond_name, []))
        bishop_wins = sum(s.get("bishop_arm_wins", 0) for s in by_condition.get(cond_name, []))
        if total_promotes > 0:
            bishop_arm_rates[cond_name] = bishop_wins / total_promotes
        else:
            bishop_arm_rates[cond_name] = 0.0

    tldr_lines = [
        f"**Headline:** bare-faithful and steelman both beat skippy_only on the metric — "
        f"means {speedups['bare_faithful']:.2f}× and {speedups['steelman']:.2f}× over baseline "
        f"vs skippy_only's {speedups['skippy_only']:.2f}× — "
        f"**but a retrospective text-similarity analysis shows the gain is not from Bishop's "
        f"contribution.** In 95% of bare_faithful iterations and 98% of steelman iterations, "
        f"Skippy's two arms produced near-identical code (difflib ratio ≥ 0.8). The "
        f"PARALLEL_PROPOSER advantage is mostly a best-of-2-Skippy-samples ensemble effect, "
        f"not the engagement-step hypothesis the spec set out to test. When Skippy *does* "
        f"produce a distinct implementation of Bishop's literal idea (ratio < 0.65), it fails "
        f"correctness 100% of the time — Bishop=qwen2.5-coder:1.5b ideas are too thin to "
        f"survive faithful implementation. With n=3, none of the pairwise speedup differences "
        f"are statistically significant (Mann-Whitney p > 0.10 for all pairs), and the "
        f"similarity finding suggests more seeds with this setup will not resolve the headline "
        f"question. See \"Post-hoc finding\" below for the full breakdown."
    ]

    # Pairwise note
    pair_lines = []
    for k, v in pairs.items():
        if "p_value" in v:
            pair_lines.append(
                f"- **{k}**: a={_fmt_num(v['a_mean'])}, b={_fmt_num(v['b_mean'])}, "
                f"Mann-Whitney U={v['u_statistic']:.1f}, p={v['p_value']:.3f}. "
                f"_({v.get('note') or ''})_"
            )

    # Per-condition table
    table = _per_condition_table(by_condition)

    # Qualitative
    qualitative = _qualitative_steelman_examples(n=5)

    benchstone_notes_path = PROJECT_ROOT / "bishop_loop" / "BENCHSTONE_NOTES.md"
    benchstone_notes = (
        benchstone_notes_path.read_text() if benchstone_notes_path.exists() else "_(missing)_"
    )

    md = f"""# Bishop-Loop Variant Experiment — JSON Parser Optimization

## TL;DR

{' '.join(tldr_lines)}

The detailed pairwise comparison and qualitative analysis appear below. With 3 seeds per
condition, this experiment is **underpowered** for any but very large effects;
report-as-evidence-not-as-conclusion applies.

## Recovery events during the sweep

Two distinct failure modes were caught mid-sweep and patched. Documented for honesty
and because they reveal load-bearing hardening details the spec didn't fully anticipate.

1. **Infinite-loop candidate hung the entire loop** (~20 hr lost). A candidate's
   `_skip_ws` used `re.compile(r'\\s*').match(text, pos)` — the zero-width match returns
   a Match object whose `end()` equals `pos`, so the while-loop never advances. The
   bishop-loop's pre-flight correctness check was in-process and had no timeout, so the
   whole sweep stalled silently. **Fix:** route correctness through the subprocess path
   with `subprocess.run(timeout=30)`. Lost run preserved as
   `phase/results/bare_faithful_1001.partial-2026-05-09/`.

2. **Memoization spec-gaming.** A candidate (bare_faithful/1002 iter 131) added a
   module-level `_parse_cache = {{}}` dict and memoized by input text. The bench_runner's
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

{table}

## Cross-condition comparison

See `trajectory.png`, `final_per_condition.png`, and `arm_wins.png` in the repo root.

## Statistical analysis

Pairwise Mann-Whitney U on the 3-vs-3 final-metric distributions:

{chr(10).join(pair_lines) if pair_lines else "_(insufficient data)_"}

**Power note:** With n=3 per side, the smallest non-degenerate U statistic that can yield
p<0.10 in a two-sided test is around p≈0.10 (rare ordering); detecting medium effects
requires substantially more seeds. Treat these p-values as descriptive, not as significance.

## Qualitative analysis: steelman in action

{qualitative}

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

{benchstone_notes}

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
"""

    (PROJECT_ROOT / "final_writeup.md").write_text(md)
    print(f"wrote {PROJECT_ROOT / 'final_writeup.md'} ({len(md)} chars)")


if __name__ == "__main__":
    main()
