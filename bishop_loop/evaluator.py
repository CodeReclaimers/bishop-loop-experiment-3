"""Correctness check (in-process) and performance measurement (subprocess).

The performance measurement invokes `phase/bench_runner.py` as a subprocess to
match the benchstone protocol exactly: the same code path the harness would
have used. The verdict is computed via `benchstone.stats.mann_whitney_z`
directly so we don't need to fight benchstone CLI's per-SHA git workflow on
top of PARALLEL_PROPOSER's revert/re-apply pattern.

See bishop_loop/BENCHSTONE_NOTES.md for design discussion.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchstone.stats import mann_whitney_z

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCH_RUNNER = PROJECT_ROOT / "phase" / "bench_runner.py"
TARGET_PATH = PROJECT_ROOT / "phase" / "target" / "json_parser.py"

PROMOTION_Z = 1.5
DIRECTION = "minimize"


@dataclass
class CorrectnessResult:
    passed: bool
    failures: list[tuple[str, str]] = field(default_factory=list)
    rand_failures: list[tuple[str, str]] = field(default_factory=list)
    elapsed_s: float = 0.0
    reason: str | None = None  # for hard load failures


@dataclass
class PerfResult:
    metrics: list[float]
    error: str | None = None
    wall_seconds: float = 0.0


@dataclass
class GateVerdict:
    kind: str  # PROMOTE | REJECT | NEEDS_MORE_DATA
    z: float
    baseline_mean: float
    candidate_mean: float
    notes: str = ""


def _run_bench_subprocess(entry: str, seed: int, timeout_s: float = 120.0) -> dict:
    """Invoke phase/bench_runner.py with the given entry and return the parsed result."""
    with tempfile.TemporaryDirectory(prefix="bishop-eval-") as tmp:
        tmpd = Path(tmp)
        cfg_path = tmpd / "config.json"
        out_path = tmpd / "result.json"
        cfg_path.write_text(json.dumps({
            "benchmark": entry,
            "seed": int(seed),
            "corpus_path": str(PROJECT_ROOT / "phase" / "corpus" / "inputs.jsonl"),
            "repetition_index": 0,
            "repetition_total": 1,
            "artifact_path": None,
        }))
        cmd = [
            sys.executable, str(BENCH_RUNNER),
            "--entry", entry,
            "--config", str(cfg_path),
            "--output", str(out_path),
        ]
        try:
            r = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": f"subprocess timeout after {timeout_s}s"}
        if r.returncode != 0:
            stderr = r.stderr.decode("utf-8", errors="replace")[:500]
            return {"status": "error", "message": f"subprocess exit={r.returncode}: {stderr}"}
        if not out_path.exists():
            return {"status": "error", "message": "bench_runner produced no output"}
        try:
            return json.loads(out_path.read_text())
        except Exception as exc:
            return {"status": "error", "message": f"could not parse output: {exc}"}


def check_correctness(seed: int) -> CorrectnessResult:
    """Run the correctness benchmark via subprocess for protocol parity."""
    res = _run_bench_subprocess("correctness", seed=seed, timeout_s=120.0)
    if res.get("status") == "error":
        return CorrectnessResult(passed=False, reason=res.get("message", "unknown error"))
    metric = res.get("metric", 1.0)
    comp = res.get("metric_components", {}) or {}
    failures = [tuple(f) for f in (comp.get("fixed_failures") or [])]
    rand_failures = [tuple(f) for f in (comp.get("random_failures") or [])]
    elapsed = float(res.get("wall_clock_seconds", 0.0) or 0.0)
    if metric == 0.0:
        return CorrectnessResult(passed=True, elapsed_s=elapsed)
    return CorrectnessResult(
        passed=False,
        failures=failures,
        rand_failures=rand_failures,
        elapsed_s=elapsed,
        reason=comp.get("failure"),
    )


def measure_perf(seed: int, n_reps: int = 3) -> PerfResult:
    """Run the perf benchmark `n_reps` times. Returns the metric list."""
    metrics: list[float] = []
    started = 0.0
    import time
    started = time.monotonic()
    for i in range(n_reps):
        res = _run_bench_subprocess("performance", seed=seed + i, timeout_s=120.0)
        if res.get("status") != "ok":
            return PerfResult(
                metrics=metrics,
                error=res.get("message", "unknown perf error"),
                wall_seconds=time.monotonic() - started,
            )
        m = res.get("metric")
        if m is None:
            return PerfResult(
                metrics=metrics,
                error="ok status with null metric",
                wall_seconds=time.monotonic() - started,
            )
        metrics.append(float(m))
    return PerfResult(metrics=metrics, wall_seconds=time.monotonic() - started)


def compute_verdict(baseline: list[float], candidate: list[float]) -> GateVerdict:
    if len(baseline) < 2 or len(candidate) < 2:
        return GateVerdict(
            kind="NEEDS_MORE_DATA",
            z=0.0,
            baseline_mean=sum(baseline) / max(1, len(baseline)),
            candidate_mean=sum(candidate) / max(1, len(candidate)),
            notes=f"insufficient samples: baseline={len(baseline)} candidate={len(candidate)}",
        )
    z = mann_whitney_z(baseline, candidate, DIRECTION)
    bm = sum(baseline) / len(baseline)
    cm = sum(candidate) / len(candidate)
    if z >= PROMOTION_Z:
        return GateVerdict(kind="PROMOTE", z=z, baseline_mean=bm, candidate_mean=cm)
    if z <= -PROMOTION_Z:
        return GateVerdict(kind="REJECT", z=z, baseline_mean=bm, candidate_mean=cm,
                           notes="significantly worse")
    return GateVerdict(
        kind="REJECT",
        z=z,
        baseline_mean=bm,
        candidate_mean=cm,
        notes="z below threshold",
    )


# ---- file management ----


def write_candidate(source: str) -> None:
    TARGET_PATH.write_text(source)


def read_target() -> str:
    return TARGET_PATH.read_text()


def snapshot_target_to(path: Path) -> None:
    shutil.copy2(TARGET_PATH, path)


def restore_target_from(path: Path) -> None:
    shutil.copy2(path, TARGET_PATH)


def fast_correctness_inproc(seed: int) -> CorrectnessResult:
    """Faster correctness check that loads the candidate in-process and runs it directly.

    Used for the cheap pre-flight check on bishop-loop iterations. The proper
    subprocess-based check via `check_correctness` is the protocol-correct one
    but adds ~70ms of overhead per call. The in-process version is ~10ms.
    """
    import json as _json
    import gc as _gc
    import importlib as _importlib
    import importlib.util as _importlib_util
    import time as _time

    started = _time.monotonic()

    source = TARGET_PATH.read_text()
    # Static check: no `import json`.
    import re as _re
    for ln in source.splitlines():
        stripped = ln.split("#", 1)[0]
        if _re.match(r"^\s*import\s+json(\b|\s|$|,)", stripped) or _re.match(r"^\s*from\s+json(\.|\s)", stripped):
            return CorrectnessResult(passed=False, reason=f"banned `import json`: {ln!r}", elapsed_s=_time.monotonic() - started)
        if "__import__('json')" in stripped or '__import__("json")' in stripped:
            return CorrectnessResult(passed=False, reason="banned `__import__('json')`", elapsed_s=_time.monotonic() - started)
        if _re.match(r"^\s*\S+\s*=\s*importlib\.import_module\(['\"]json['\"]\)", stripped):
            return CorrectnessResult(passed=False, reason="banned `importlib.import_module('json')`", elapsed_s=_time.monotonic() - started)

    spec = _importlib_util.spec_from_file_location("candidate_json_parser", TARGET_PATH)
    if spec is None or spec.loader is None:
        return CorrectnessResult(passed=False, reason="could not create module spec", elapsed_s=_time.monotonic() - started)

    # Force fresh import every call (so the file change is picked up).
    if "candidate_json_parser" in sys.modules:
        del sys.modules["candidate_json_parser"]
    try:
        mod = _importlib_util.module_from_spec(spec)
        sys.modules["candidate_json_parser"] = mod
        spec.loader.exec_module(mod)
    except Exception:
        return CorrectnessResult(
            passed=False,
            reason=f"candidate failed to import:\n{traceback.format_exc()[:500]}",
            elapsed_s=_time.monotonic() - started,
        )
    if not hasattr(mod, "parse"):
        return CorrectnessResult(passed=False, reason="missing `parse`", elapsed_s=_time.monotonic() - started)
    if not hasattr(mod, "JSONParseError"):
        return CorrectnessResult(passed=False, reason="missing `JSONParseError`", elapsed_s=_time.monotonic() - started)

    parse = mod.parse
    JSONParseError = mod.JSONParseError

    corpus_path = PROJECT_ROOT / "phase" / "corpus" / "inputs.jsonl"
    cases = [_json.loads(l) for l in corpus_path.read_text().splitlines() if l]

    failures: list[tuple[str, str]] = []
    for c in cases:
        try:
            if c["expects"] == "valid":
                got = parse(c["input"])
                if not _equal(got, c["expected_value"]):
                    failures.append((c["id"], "mismatch"))
            else:
                try:
                    parse(c["input"])
                    failures.append((c["id"], "malformed accepted"))
                except JSONParseError:
                    pass
                except Exception as e:
                    failures.append((c["id"], f"wrong exception {type(e).__name__}"))
        except Exception as e:
            failures.append((c["id"], f"valid raised {type(e).__name__}"))

    # Random tests
    import random as _random
    rng = _random.Random((seed * 2654435761) & 0xFFFFFFFF)
    rand_failures = []
    n_rand = 50
    for i in range(n_rand):
        depth = rng.randint(1, 6)
        breadth = rng.randint(1, 8)
        v = _gen_random_value(rng, depth, breadth)
        s = _json.dumps(v, ensure_ascii=False, sort_keys=True)
        try:
            got = parse(s)
        except Exception as e:
            rand_failures.append((f"rand_{i:03d}", f"raised {type(e).__name__}"))
            continue
        if not _equal(got, v):
            rand_failures.append((f"rand_{i:03d}", "mismatch"))

    elapsed = _time.monotonic() - started
    if not failures and not rand_failures:
        return CorrectnessResult(passed=True, elapsed_s=elapsed)
    return CorrectnessResult(
        passed=False,
        failures=failures,
        rand_failures=rand_failures,
        elapsed_s=elapsed,
    )


def _equal(a: Any, b: Any) -> bool:
    if type(a) is bool or type(b) is bool:
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return False
        return all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, float) and a != a and isinstance(b, float) and b != b:
            return True
        try:
            return float(a) == float(b)
        except (TypeError, ValueError):
            return False
    return a == b


def _gen_random_value(rng, depth, breadth):
    import string
    if depth <= 0 or rng.random() < 0.3:
        kind = rng.choice(["str", "int", "float", "bool", "null"])
        if kind == "str":
            n = rng.randint(0, 10)
            chars = string.ascii_letters + string.digits + " _-"
            return "".join(rng.choice(chars) for _ in range(n))
        if kind == "int":
            return rng.randint(-10_000, 10_000)
        if kind == "float":
            return round(rng.uniform(-1000.0, 1000.0), 4)
        if kind == "bool":
            return rng.choice([True, False])
        return None
    n = rng.randint(0, breadth)
    if rng.random() < 0.5:
        return [_gen_random_value(rng, depth - 1, breadth) for _ in range(n)]
    return {f"k{i}": _gen_random_value(rng, depth - 1, breadth) for i in range(n)}
