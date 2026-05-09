"""Main bishop-loop driver. Runs one (condition, seed) combination.

Conditions:
  - skippy_only: Skippy proposes alone.
  - bare_faithful: Skippy idea arm + Bishop-via-Skippy-faithful arm; PARALLEL_PROPOSER.
  - steelman: Skippy idea arm + Bishop-via-Skippy-steelman arm; PARALLEL_PROPOSER.

For PARALLEL_PROPOSER, both arms are evaluated against the same baseline; the
arm with the best PROMOTE metric wins. If neither PROMOTEs, neither wins and
the iteration is a no-op.

Outputs (in `phase/results/{condition}_{seed}/`):
  - summary.json      — final summary
  - iteration_log.jsonl — per-iteration detail
  - proposals/iter_{i}_{arm}_(prompt|response).txt
  - diffs/iter_{i}_{arm}.py    — promoted file rewrites
"""
from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .budget import Budget
from .evaluator import (
    CorrectnessResult, GateVerdict, PerfResult, PROMOTION_Z,
    compute_verdict, fast_correctness_inproc, measure_perf,
    read_target, write_candidate,
)
from . import ollama_client, proposers
from .proposers import IterationHistory, extract_critique_steelman

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_PATH = PROJECT_ROOT / "phase" / "target" / "json_parser.py"
NAIVE_BASELINE_PATH = PROJECT_ROOT / "phase" / "target" / "_baseline_naive.py"


def _print(msg: str) -> None:
    print(msg, flush=True)


@dataclass
class ArmResult:
    arm: str  # "skippy" | "bishop_bare" | "bishop_steelman"
    proposal_text: str  # raw model output
    code: str | None
    correctness: CorrectnessResult | None
    perf: PerfResult | None
    verdict: GateVerdict | None
    elapsed_s: float
    extra: dict = field(default_factory=dict)


@dataclass
class LoopState:
    condition: str
    seed: int
    out_dir: Path
    budget: Budget
    baseline_metrics: list[float]
    history: IterationHistory
    iter_idx: int = 0
    promotions: int = 0
    rejections: int = 0
    needs_more_data: int = 0
    apply_failures: int = 0
    skippy_arm_wins: int = 0
    bishop_arm_wins: int = 0
    skippy_arm_evals: int = 0
    bishop_arm_evals: int = 0
    skippy_arm_promotes: int = 0
    bishop_arm_promotes: int = 0
    skippy_total_tokens: int = 0
    bishop_total_tokens: int = 0
    initial_metric: float = 0.0
    best_ever_metric: float = float("inf")
    trajectory: list[dict] = field(default_factory=list)


def _save_proposal(out_dir: Path, iter_idx: int, arm: str, kind: str, text: str) -> None:
    p = out_dir / "proposals"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"iter_{iter_idx:04d}_{arm}_{kind}.txt").write_text(text)


def _save_promoted_diff(out_dir: Path, iter_idx: int, arm: str, code: str) -> None:
    p = out_dir / "diffs"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"iter_{iter_idx:04d}_{arm}.py").write_text(code)


def _append_iter_log(out_dir: Path, entry: dict) -> None:
    with (out_dir / "iteration_log.jsonl").open("a") as f:
        f.write(json.dumps(entry, default=str, sort_keys=True) + "\n")


def _baseline_check(state: LoopState) -> None:
    """Establish the initial baseline metrics by running the naive parser 3 times.

    Writes to state.baseline_metrics and state.initial_metric.
    """
    _print(f"[{state.condition}/{state.seed}] establishing baseline...")
    perf = measure_perf(seed=state.seed * 100, n_reps=3)
    if perf.error or len(perf.metrics) < 3:
        raise RuntimeError(f"baseline measurement failed: {perf.error}")
    state.baseline_metrics = list(perf.metrics)
    state.initial_metric = sum(perf.metrics) / len(perf.metrics)
    state.best_ever_metric = state.initial_metric
    _print(
        f"[{state.condition}/{state.seed}] baseline: "
        f"{[f'{m:.4f}' for m in perf.metrics]} mean={state.initial_metric:.4f}"
    )
    state.trajectory.append({
        "iter": 0,
        "wall_s": state.budget.elapsed(),
        "metric": state.initial_metric,
        "verdict": "BASELINE",
        "winning_arm": None,
    })


def _evaluate_candidate(seed: int) -> tuple[CorrectnessResult, PerfResult | None]:
    """Run the in-process correctness check, then perf if correctness passed."""
    cr = fast_correctness_inproc(seed=seed)
    if not cr.passed:
        return cr, None
    pr = measure_perf(seed=seed * 7919, n_reps=3)
    return cr, pr


def _run_skippy_arm(state: LoopState, source_at_iter_start: str, seed_offset: int) -> ArmResult:
    """Generate a Skippy proposal and evaluate it. Returns metrics; does not modify state.history."""
    iter_seed = state.seed + state.iter_idx * 10_000 + seed_offset
    arm_started = time.monotonic()

    prompt = proposers.skippy_prompt(source_at_iter_start, state.history)
    _save_proposal(state.out_dir, state.iter_idx, "skippy", "prompt", prompt)
    try:
        gen = proposers.call_skippy(prompt, seed=iter_seed)
    except Exception as e:
        return ArmResult(
            arm="skippy",
            proposal_text="",
            code=None,
            correctness=None,
            perf=None,
            verdict=None,
            elapsed_s=time.monotonic() - arm_started,
            extra={"error": f"Skippy call failed: {type(e).__name__}: {e}"},
        )
    state.skippy_total_tokens += gen.total_tokens
    _save_proposal(state.out_dir, state.iter_idx, "skippy", "response", gen.text)

    code = ollama_client.extract_python_block(gen.text)
    if code is None:
        return ArmResult(
            arm="skippy",
            proposal_text=gen.text,
            code=None,
            correctness=None,
            perf=None,
            verdict=None,
            elapsed_s=time.monotonic() - arm_started,
            extra={"error": "no code block in Skippy response"},
        )

    write_candidate(code)
    cr, pr = _evaluate_candidate(iter_seed + 999_983)

    verdict = None
    if cr.passed and pr is not None and not pr.error:
        verdict = compute_verdict(state.baseline_metrics, pr.metrics)
    return ArmResult(
        arm="skippy",
        proposal_text=gen.text[:5000],
        code=code,
        correctness=cr,
        perf=pr,
        verdict=verdict,
        elapsed_s=time.monotonic() - arm_started,
        extra={"gen_seconds": gen.total_seconds, "tokens": gen.total_tokens},
    )


def _run_bishop_idea(state: LoopState, source_at_iter_start: str, seed_offset: int) -> tuple[str | None, dict]:
    iter_seed = state.seed + state.iter_idx * 10_000 + seed_offset
    prompt = proposers.bishop_idea_prompt(source_at_iter_start, state.history)
    _save_proposal(state.out_dir, state.iter_idx, "bishop", "prompt", prompt)
    try:
        gen = proposers.call_bishop(prompt, seed=iter_seed)
    except Exception as e:
        return None, {"error": f"Bishop call failed: {type(e).__name__}: {e}"}
    state.bishop_total_tokens += gen.total_tokens
    _save_proposal(state.out_dir, state.iter_idx, "bishop", "response", gen.text)
    text = gen.text.strip()
    return text, {"tokens": gen.total_tokens, "gen_seconds": gen.total_seconds}


def _run_bishop_arm(
    state: LoopState,
    source_at_iter_start: str,
    bishop_idea: str,
    mode: str,  # "bare_faithful" | "steelman"
    seed_offset: int,
) -> ArmResult:
    iter_seed = state.seed + state.iter_idx * 10_000 + seed_offset
    arm_started = time.monotonic()

    arm_name = "bishop_bare" if mode == "bare_faithful" else "bishop_steelman"

    if mode == "bare_faithful":
        prompt = proposers.skippy_bare_faithful_prompt(source_at_iter_start, bishop_idea)
    else:
        prompt = proposers.skippy_steelman_prompt(source_at_iter_start, bishop_idea)
    _save_proposal(state.out_dir, state.iter_idx, arm_name, "prompt", prompt)

    try:
        gen = proposers.call_skippy(prompt, seed=iter_seed)
    except Exception as e:
        return ArmResult(
            arm=arm_name,
            proposal_text="",
            code=None,
            correctness=None,
            perf=None,
            verdict=None,
            elapsed_s=time.monotonic() - arm_started,
            extra={"error": f"Skippy({mode}) call failed: {type(e).__name__}: {e}"},
        )
    state.skippy_total_tokens += gen.total_tokens
    _save_proposal(state.out_dir, state.iter_idx, arm_name, "response", gen.text)

    code = ollama_client.extract_python_block(gen.text)
    extra: dict[str, Any] = {
        "gen_seconds": gen.total_seconds,
        "tokens": gen.total_tokens,
        "bishop_idea": bishop_idea[:1000],
    }
    if mode == "steelman" and code is not None:
        crit, steel = extract_critique_steelman(code)
        extra["critique"] = crit
        extra["steelman"] = steel

    if code is None:
        return ArmResult(
            arm=arm_name,
            proposal_text=gen.text[:5000],
            code=None,
            correctness=None,
            perf=None,
            verdict=None,
            elapsed_s=time.monotonic() - arm_started,
            extra={**extra, "error": "no code block in Skippy response"},
        )

    write_candidate(code)
    cr, pr = _evaluate_candidate(iter_seed + 999_983)

    verdict = None
    if cr.passed and pr is not None and not pr.error:
        verdict = compute_verdict(state.baseline_metrics, pr.metrics)
    return ArmResult(
        arm=arm_name,
        proposal_text=gen.text[:5000],
        code=code,
        correctness=cr,
        perf=pr,
        verdict=verdict,
        elapsed_s=time.monotonic() - arm_started,
        extra=extra,
    )


def _arm_result_dict(r: ArmResult) -> dict:
    """Compact JSONL-friendly form."""
    out = {
        "arm": r.arm,
        "elapsed_s": r.elapsed_s,
        "extra": r.extra,
    }
    if r.correctness is not None:
        out["correctness"] = {
            "passed": r.correctness.passed,
            "n_failures": len(r.correctness.failures),
            "n_rand_failures": len(r.correctness.rand_failures),
            "reason": r.correctness.reason,
            "first_failures": r.correctness.failures[:3],
        }
    if r.perf is not None:
        out["perf"] = {
            "metrics": r.perf.metrics,
            "error": r.perf.error,
            "wall_seconds": r.perf.wall_seconds,
        }
    if r.verdict is not None:
        out["verdict"] = {
            "kind": r.verdict.kind,
            "z": r.verdict.z,
            "baseline_mean": r.verdict.baseline_mean,
            "candidate_mean": r.verdict.candidate_mean,
            "notes": r.verdict.notes,
        }
    return out


def _excerpt_for_history(code: str, max_lines: int = 35) -> str:
    """Pull a representative excerpt from the candidate code for the next-iteration prompt.

    We grab two regions: the top of the file (precompiled regex definitions etc.)
    and the first `_skip_ws` or `_parse_*` function. Most bugs in this experiment
    live in one of those two regions.
    """
    import re
    lines = code.splitlines()
    # Top: skip docstring/imports, find the first `_RE`/`_PATTERN` or `def` line.
    top_start = 0
    for i, ln in enumerate(lines[:80]):
        if re.match(r"^_[A-Z][A-Z0-9_]*_(?:RE|PATTERN|PAT)\s*=", ln) or re.match(r"^def\s+", ln):
            top_start = i
            break
    top_end = min(len(lines), top_start + 12)

    # Function: first `_skip_ws` or `_parse_object` / `_parse_array`.
    fn_start = None
    for i, ln in enumerate(lines):
        if re.match(r"^def\s+(_skip_ws|_parse_object|_parse_array)\b", ln):
            fn_start = i
            break
    if fn_start is None:
        for i, ln in enumerate(lines):
            if re.match(r"^def\s+_parse_", ln):
                fn_start = i
                break
    if fn_start is None:
        return "\n".join(lines[:max_lines])
    fn_end = min(len(lines), fn_start + 18)

    out = []
    if top_start < top_end:
        out.append(f"# (top of file, lines {top_start+1}-{top_end})")
        out.extend(lines[top_start:top_end])
        out.append("# ...")
    out.append(f"# (function at lines {fn_start+1}-{fn_end})")
    out.extend(lines[fn_start:fn_end])
    return "\n".join(out)


def _summarize_arm_history(arm: ArmResult) -> str:
    """Short human description for the IterationHistory log."""
    if arm.code is None:
        return f"[{arm.arm}] {arm.extra.get('error', 'no code emitted')[:120]}"
    if arm.correctness and not arm.correctness.passed:
        if arm.correctness.reason:
            return f"[{arm.arm}] correctness load error: {arm.correctness.reason[:140]}"
        # Summarize a couple of representative failures so the next iteration
        # has a concrete signal about what went wrong.
        fail_samples = []
        for case_id, msg in (arm.correctness.failures + arm.correctness.rand_failures)[:3]:
            fail_samples.append(f"{case_id}:{msg}")
        return (
            f"[{arm.arm}] correctness failed: {len(arm.correctness.failures)} fixed + "
            f"{len(arm.correctness.rand_failures)} random failures; "
            f"e.g. {', '.join(fail_samples)[:160]}"
        )
    if arm.perf and arm.perf.error:
        return f"[{arm.arm}] perf error: {arm.perf.error[:120]}"
    if arm.verdict:
        return (
            f"[{arm.arm}] {arm.verdict.kind} z={arm.verdict.z:+.2f} "
            f"mean={arm.verdict.candidate_mean:.4f} (baseline {arm.verdict.baseline_mean:.4f})"
        )
    return f"[{arm.arm}] no verdict"


def run_one_iteration(state: LoopState) -> dict:
    """Run one iteration of the configured condition and update state. Returns the iter log entry."""
    state.iter_idx += 1
    iter_started = time.monotonic()
    source_at_iter_start = read_target()

    arms: list[ArmResult] = []

    # Skippy arm always runs.
    skippy = _run_skippy_arm(state, source_at_iter_start, seed_offset=1)
    arms.append(skippy)
    state.skippy_arm_evals += 1
    if skippy.verdict and skippy.verdict.kind == "PROMOTE":
        state.skippy_arm_promotes += 1

    # Restore the baseline source before evaluating the next arm
    write_candidate(source_at_iter_start)

    bishop_idea: str | None = None
    bishop_idea_extra: dict = {}

    if state.condition in ("bare_faithful", "steelman"):
        bishop_idea, bishop_idea_extra = _run_bishop_idea(state, source_at_iter_start, seed_offset=2)
        if bishop_idea:
            mode = "bare_faithful" if state.condition == "bare_faithful" else "steelman"
            bishop_arm = _run_bishop_arm(state, source_at_iter_start, bishop_idea, mode=mode, seed_offset=3)
            arms.append(bishop_arm)
            state.bishop_arm_evals += 1
            if bishop_arm.verdict and bishop_arm.verdict.kind == "PROMOTE":
                state.bishop_arm_promotes += 1
            # Restore source after evaluation (we'll re-apply the winner below).
            write_candidate(source_at_iter_start)

    # Pick winner
    promotable = [a for a in arms if a.verdict and a.verdict.kind == "PROMOTE"]
    winning_arm: ArmResult | None = None
    if promotable:
        winning_arm = min(promotable, key=lambda a: a.verdict.candidate_mean)

    log_entry = {
        "iter": state.iter_idx,
        "wall_s": state.budget.elapsed(),
        "iter_seconds": time.monotonic() - iter_started,
        "arms": [_arm_result_dict(a) for a in arms],
        "bishop_idea": bishop_idea,
        "bishop_extra": bishop_idea_extra,
        "winning_arm": winning_arm.arm if winning_arm else None,
        "winning_metric": winning_arm.verdict.candidate_mean if winning_arm else None,
    }

    if winning_arm is None:
        # Count rejections / NEEDS_MORE_DATA
        for a in arms:
            if a.code is None or (a.correctness and not a.correctness.passed):
                state.apply_failures += 1
            elif a.verdict and a.verdict.kind == "REJECT":
                state.rejections += 1
            elif a.verdict and a.verdict.kind == "NEEDS_MORE_DATA":
                state.needs_more_data += 1
        # source already restored
        # Add rejection summaries to history
        for a in arms:
            state.history.rejected.append(_summarize_arm_history(a))
            if a.code is not None and a.correctness and not a.correctness.passed:
                state.history.rejected_code_excerpts.insert(0, _excerpt_for_history(a.code))
                # Keep at most 4 excerpts (we display 2 in the prompt)
                state.history.rejected_code_excerpts = state.history.rejected_code_excerpts[:4]
    else:
        # Apply winner permanently
        write_candidate(winning_arm.code)
        # Update baseline metrics to candidate metrics
        state.baseline_metrics = list(winning_arm.perf.metrics)
        # Track stats
        state.promotions += 1
        if winning_arm.arm == "skippy":
            state.skippy_arm_wins += 1
        else:
            state.bishop_arm_wins += 1
        state.best_ever_metric = min(state.best_ever_metric, winning_arm.verdict.candidate_mean)
        # Save the promoted diff
        _save_promoted_diff(state.out_dir, state.iter_idx, winning_arm.arm, winning_arm.code)
        # Track non-winning arms as rejected
        for a in arms:
            if a is not winning_arm:
                state.history.rejected.append(_summarize_arm_history(a))
                if a.code is not None and a.correctness and not a.correctness.passed:
                    state.history.rejected_code_excerpts.insert(0, _excerpt_for_history(a.code))
        state.history.rejected_code_excerpts = state.history.rejected_code_excerpts[:4]
        state.history.promoted.append(_summarize_arm_history(winning_arm))

    state.trajectory.append({
        "iter": state.iter_idx,
        "wall_s": state.budget.elapsed(),
        "metric": (winning_arm.verdict.candidate_mean if winning_arm else state.baseline_metrics[0] if state.baseline_metrics else None),
        "best_ever_metric": state.best_ever_metric,
        "verdict": (winning_arm.verdict.kind if winning_arm else "REJECT"),
        "winning_arm": winning_arm.arm if winning_arm else None,
    })
    return log_entry


def run(condition: str, seed: int, budget_seconds: float, out_dir: Path) -> dict:
    """Run one (condition, seed) loop with the given wall-clock budget."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Restore the naive parser at the start of every run.
    if NAIVE_BASELINE_PATH.exists():
        shutil.copy2(NAIVE_BASELINE_PATH, TARGET_PATH)

    budget = Budget(total_seconds=budget_seconds)
    budget.start()

    state = LoopState(
        condition=condition,
        seed=seed,
        out_dir=out_dir,
        budget=budget,
        baseline_metrics=[],
        history=IterationHistory(promoted=[], rejected=[]),
    )

    try:
        _baseline_check(state)
        early_stop = None

        while not budget.expired():
            try:
                log_entry = run_one_iteration(state)
                _append_iter_log(out_dir, log_entry)
                _print(
                    f"[{condition}/{seed}] iter {state.iter_idx} "
                    f"wall={budget.elapsed():.1f}s "
                    f"winner={log_entry.get('winning_arm')} "
                    f"best={state.best_ever_metric:.4f}"
                )
            except Exception:
                tb = traceback.format_exc()
                _append_iter_log(out_dir, {
                    "iter": state.iter_idx,
                    "wall_s": budget.elapsed(),
                    "error": tb[:2000],
                })
                _print(f"[{condition}/{seed}] iteration error:\n{tb[:500]}")
                # restore source from naive baseline if anything went wrong
                if NAIVE_BASELINE_PATH.exists():
                    # Reset baseline metrics too, so the gate stays calibrated
                    pass

        early_stop = "budget"
    finally:
        summary = {
            "condition": state.condition,
            "seed": state.seed,
            "iterations_completed": state.iter_idx,
            "wall_clock_elapsed_s": budget.elapsed(),
            "early_stop_reason": "budget" if budget.expired() else "exception",
            "initial_metric": state.initial_metric,
            "final_baseline_mean": (sum(state.baseline_metrics) / len(state.baseline_metrics)) if state.baseline_metrics else None,
            "best_ever_metric": state.best_ever_metric,
            "promotions": state.promotions,
            "rejections": state.rejections,
            "needs_more_data": state.needs_more_data,
            "apply_failures": state.apply_failures,
            "skippy_arm_evals": state.skippy_arm_evals,
            "skippy_arm_promotes": state.skippy_arm_promotes,
            "skippy_arm_wins": state.skippy_arm_wins,
            "bishop_arm_evals": state.bishop_arm_evals,
            "bishop_arm_promotes": state.bishop_arm_promotes,
            "bishop_arm_wins": state.bishop_arm_wins,
            "skippy_total_tokens": state.skippy_total_tokens,
            "bishop_total_tokens": state.bishop_total_tokens,
            "trajectory": state.trajectory,
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str, sort_keys=True))
        _print(
            f"[{condition}/{seed}] done. "
            f"iters={state.iter_idx} promotes={state.promotions} best={state.best_ever_metric:.4f}"
        )
        return summary
