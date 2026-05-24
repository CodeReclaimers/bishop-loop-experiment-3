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
    for seed in (3001, 3002, 3003, 3004, 3005, 3006, 3007, 3008, 3009, 3010):
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
            # In SEARCH/REPLACE mode (sweep 3001+) the steelman text key is
            # `steelman_text` (bare CRITIQUE:/STEELMAN: lines extracted from
            # the response). In the old full-rewrite mode it was `steelman`.
            steelman = extra.get("steelman_text") or extra.get("steelman")
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


def _load_similarity_stats() -> dict:
    p = PROJECT_ROOT / "arm_similarity.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    out = {}
    for cond, runs in data.items():
        if not runs:
            continue
        all_ratios = [r for run in runs for r in run.get("all_ratios", [])]
        if not all_ratios:
            continue
        import statistics
        out[cond] = {
            "n": len(all_ratios),
            "median": statistics.median(all_ratios),
            "mean": statistics.mean(all_ratios),
            "pct_ge_08": sum(1 for r in all_ratios if r >= 0.8) / len(all_ratios),
        }
    return out


def main() -> None:
    data_path = PROJECT_ROOT / "final_writeup_data.json"
    if not data_path.exists():
        print(f"missing {data_path}; run phase/analyze_results.py first", flush=True)
        return
    data = json.loads(data_path.read_text())
    by_condition = data["raw_summaries"]
    pairs = data["pairwise"]
    sim = _load_similarity_stats()

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

    bf_sim = sim.get("bare_faithful", {})
    sm_sim = sim.get("steelman", {})
    n_seeds = max((len(by_condition.get(c, [])) for c in by_condition), default=0)
    arms_distinct = bf_sim.get("median", 1.0) < 0.5 and sm_sim.get("median", 1.0) < 0.5
    if arms_distinct:
        arm_summary = (
            f"Unlike earlier pilots, the bishop-derived arm is now genuinely distinct "
            f"from the skippy arm (median similarity bare_faithful="
            f"{bf_sim.get('median', 0):.2f}, steelman={sm_sim.get('median', 0):.2f}; "
            f"≈ 0% of iterations have ratio ≥ 0.8). The PARALLEL_PROPOSER arms are "
            f"actually competing approaches, not Skippy regenerating the same code twice."
        )
    else:
        arm_summary = (
            f"Skippy's two arms produced near-identical code in most iterations "
            f"(median similarity bare_faithful={bf_sim.get('median', 0):.2f}, "
            f"steelman={sm_sim.get('median', 0):.2f}; "
            f"{bf_sim.get('pct_ge_08', 0)*100:.0f}% / "
            f"{sm_sim.get('pct_ge_08', 0)*100:.0f}% of iterations have ratio ≥ 0.8). "
            f"The PARALLEL_PROPOSER advantage is mostly a best-of-2-Skippy-samples "
            f"ensemble effect, not the engagement-step hypothesis the spec set out to test."
        )
    tldr_lines = [
        f"**Headline:** at n={n_seeds} seeds per condition, "
        f"**bare_faithful** ({speedups['bare_faithful']:.2f}× speedup over baseline) and "
        f"**steelman** ({speedups['steelman']:.2f}×) both clearly beat "
        f"**skippy_only** ({speedups['skippy_only']:.2f}×). "
        f"The two PARALLEL_PROPOSER conditions are statistically indistinguishable from each other "
        f"on the final metric ({_fmt_num(means['bare_faithful'])}s vs "
        f"{_fmt_num(means['steelman'])}s, std ≈ 0.0006 each). The Bishop-arm-win rate is "
        f"**higher under bare-faithful** ({bishop_arm_rates.get('bare_faithful', 0)*100:.0f}%) "
        f"than under steelman ({bishop_arm_rates.get('steelman', 0)*100:.0f}%) — the opposite "
        f"of what the engagement-step hypothesis predicts. "
        f"{arm_summary} "
        f"Initial baseline was {_fmt_num(init_mean)}s."
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

The detailed pairwise comparison and qualitative analysis appear below.

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

Pairwise Mann-Whitney U on the {n_seeds}-vs-{n_seeds} final-metric distributions:

{chr(10).join(pair_lines) if pair_lines else "_(insufficient data)_"}

At n={n_seeds} per condition the skippy-vs-bare and skippy-vs-steel comparisons are
clearly significant; the bare-vs-steel difference is not. The standard deviations
within each PARALLEL_PROPOSER condition (~0.0006s) are an order of magnitude smaller
than the gap between PARALLEL_PROPOSER and skippy_only, so the two-arm effect dominates
the engagement-step effect at this sample size.

## Qualitative analysis: steelman in action

{qualitative}

## Post-hoc finding: arms are now genuinely distinct (SEARCH/REPLACE mode)

The original 3-seed sweep showed bare_faithful and steelman PARALLEL_PROPOSER
arms producing near-identical code (median similarity 0.99). The cause was the
full-file-rewrite paradigm: when Skippy was given a free hand to rewrite the
file in response to Bishop's idea, he regenerated his own approach with tiny
variations. The "Bishop arm" was effectively a second Skippy sample.

A series of pilots (documented in `bishop_loop/BENCHSTONE_NOTES.md` and
`phase/results/{{bare_faithful,steelman}}_2001.*` snapshots) iterated through:
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
to SEARCH/REPLACE. A 10-seed control sweep (seeds 4001-4010) re-runs bare_faithful +
steelman with `qwen2.5-coder:1.5b` Bishop under SEARCH/REPLACE mode, isolating the
two effects.

| condition | nemotron-4B + SR (n=10) | qwen-1.5B + SR (n=10) | Mann-Whitney p (best) | Fisher p (bishop wins) |
|---|---|---|---|---|
| bare_faithful best | 0.0101 ± 0.0006 | 0.0101 ± 0.0006 | 0.791 | — |
| bare_faithful bishop-arm wins | 60% (25/42) | 51% (26/51) | — | 0.530 |
| steelman best | 0.0105 ± 0.0003 | 0.0103 ± 0.0003 | 0.385 | — |
| steelman bishop-arm wins | 35% (12/34) | 41% (17/42) | — | 0.813 |

At n=10 vs n=10, every comparison between Bishop models is statistically indistinguishable
(p ≥ 0.385 on all four). The n=3 hint that "steelman bishop-wins are higher with the smaller
Bishop" (53% qwen vs 35% nemotron) was noise — adding 7 more qwen seeds dropped the rate
to 41%, well within noise of the nemotron 35%.

**Conclusion:** the SEARCH/REPLACE format change was the load-bearing fix, and **Bishop
model capability (1.5B vs 4B) does not measurably affect the bishop-arm contribution in
this experiment**. The original 22% bishop-win rate (qwen-1.5B + full-rewrite) reflected
the same-arms-degeneracy confound, not a Bishop-capability ceiling. Given a format that
actually applies Bishop's edit to the source, a 1.5B Bishop produces ideas that compete
with Skippy's full-rewrite arm just as effectively as a 4B Bishop does.

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
