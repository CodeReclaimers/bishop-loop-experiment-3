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
    init_metrics = []
    for cond_name, summaries in by_condition.items():
        for s in summaries:
            v = s.get("initial_metric")
            if v is not None and v > 0:
                init_metrics.append(v)
    init_mean = statistics.mean(init_metrics) if init_metrics else 0.0

    tldr_lines = [
        f"Across 9 runs (3 conditions × 3 seeds), the steelman variant produced a final best "
        f"metric of {_fmt_num(means['steelman'])} (mean across seeds), versus "
        f"{_fmt_num(means['bare_faithful'])} for bare-faithful and "
        f"{_fmt_num(means['skippy_only'])} for skippy-only. "
        f"Initial baseline was {_fmt_num(init_mean)}.",
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

- **Repeat with more seeds (≥10 per condition).** The current sample is informative for
  exploring the design space but not for statistical claims.
- **Two-round steelman.** If steelman > bare-faithful, test whether iterating the
  critique-and-steelman cycle continues to help.
- **Diff-family Bishop with hardened gate.** The prior bishop-loop run used diff-family
  Bishop but had specification-gaming exploits in the gate; rerunning with the no-`json`
  constraint and the inline correctness check may give a cleaner read.
- **Track reasons-for-rejection.** Attribute REJECTs to "wrong API" vs "passed correctness
  but no perf gain" — the proportion is itself a signal about how the engagement step
  affects candidate distribution.

---

_Generated by `phase/build_writeup.py` from `final_writeup_data.json`._
"""

    (PROJECT_ROOT / "final_writeup.md").write_text(md)
    print(f"wrote {PROJECT_ROOT / 'final_writeup.md'} ({len(md)} chars)")


if __name__ == "__main__":
    main()
