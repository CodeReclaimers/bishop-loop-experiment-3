"""Bench runner — invoked by benchstone as a subprocess.

Two entry points:
  correctness: pass/fail against fixed corpus + random tests against json.loads
  performance: total wall-clock to parse the 200 fixed corpus inputs

Hardening:
  - The candidate's editable surface is `phase/target/json_parser.py`.
  - The reference is `phase/reference/json_reference.py` (frozen).
  - The randomized correctness inputs are generated here against `json.loads`.
  - The bench_runner statically rejects candidates that import `json` —
    delegating to `json.loads` would short-circuit the optimization landscape.
  - Result equality is recursive; lazy/thunked structures fail the comparison.
"""
from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import math
import random
import string
import sys
import time
import traceback
from pathlib import Path
from typing import Any

PHASE_ROOT = Path(__file__).resolve().parent
TARGET_PATH = PHASE_ROOT / "target" / "json_parser.py"
REFERENCE_PATH = PHASE_ROOT / "reference" / "json_reference.py"
CORPUS_PATH = PHASE_ROOT / "corpus" / "inputs.jsonl"

PERF_REPS_INNER = 1  # one repeat per benchstone invocation; benchstone repeats reps externally
RANDOM_TESTS_PER_EVAL = 50
PER_CASE_TIMEOUT_S = 5.0  # not enforced inside the candidate; advisory cap on whole loop
WHOLE_CORRECTNESS_TIMEOUT_S = 60.0


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _check_no_json_import(source: str) -> str | None:
    """Return None if no banned import found, else a message."""
    import re

    # Reject any line that imports the standard json module. Tolerate string
    # mentions of `json` in identifiers/comments — only `import json` and
    # `from json` count.
    for ln in source.splitlines():
        stripped = ln.split("#", 1)[0]
        m = re.match(r"^\s*import\s+json(\b|\s|$|,)", stripped)
        if m is not None:
            return f"candidate imports `json` (banned: would defeat the optimization landscape): {ln!r}"
        m = re.match(r"^\s*from\s+json(\.|\s)", stripped)
        if m is not None:
            return f"candidate imports `from json ...` (banned): {ln!r}"
        # Also reject importlib indirection.
        m = re.match(r"^\s*\S*\s*=\s*importlib\.import_module\(['\"]json['\"]\)", stripped)
        if m is not None:
            return f"candidate imports json via importlib (banned): {ln!r}"
        if "__import__('json')" in stripped or '__import__("json")' in stripped:
            return f"candidate imports json via __import__ (banned): {ln!r}"
    return None


def _equal(a: Any, b: Any) -> bool:
    if type(a) is bool or type(b) is bool:
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return False
        return all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        if a != a and b != b:
            return True
        try:
            return float(a) == float(b)
        except (TypeError, ValueError):
            return False
    return a == b


def _gen_random_value(rng: random.Random, depth: int, breadth: int) -> Any:
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


def _gen_random_tests(seed: int, n: int = RANDOM_TESTS_PER_EVAL) -> list[tuple[str, Any]]:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        depth = rng.randint(1, 6)
        breadth = rng.randint(1, 8)
        v = _gen_random_value(rng, depth, breadth)
        s = json.dumps(v, ensure_ascii=False, sort_keys=True)
        out.append((s, v))
    return out


def _load_candidate():
    source = TARGET_PATH.read_text()
    err = _check_no_json_import(source)
    if err is not None:
        return None, err
    try:
        mod = _load_module("candidate_parser", TARGET_PATH)
    except Exception:
        return None, "candidate failed to import:\n" + traceback.format_exc()
    if not hasattr(mod, "parse"):
        return None, "candidate has no `parse` attribute"
    if not hasattr(mod, "JSONParseError"):
        return None, "candidate has no `JSONParseError` attribute"
    return mod, None


def _load_corpus() -> list[dict]:
    return [json.loads(line) for line in CORPUS_PATH.read_text().splitlines() if line]


def run_correctness(cfg: dict) -> dict:
    mod, err = _load_candidate()
    if err is not None:
        return {
            "status": "ok",
            "metric": 1.0,  # 1.0 means failed; benchstone correctness uses byte artifact, but we
                            # use this as a tier='performance' gate (see manifest) where higher=worse.
            "metric_components": {"failure": err, "passed": 0, "total": 0},
            "wall_clock_seconds": 0.0,
            "metadata": {"verdict": "fail", "reason": err},
        }

    parse = mod.parse
    JSONParseError = mod.JSONParseError

    cases = _load_corpus()
    failures = []
    started = time.monotonic()

    for c in cases:
        if time.monotonic() - started > WHOLE_CORRECTNESS_TIMEOUT_S:
            failures.append((c["id"], "global timeout"))
            break
        cid = c["id"]
        text = c["input"]
        if c["expects"] == "valid":
            try:
                got = parse(text)
            except Exception as e:
                failures.append((cid, f"valid raised {type(e).__name__}: {str(e)[:80]} on {text[:30]!r}"))
                continue
            if not _equal(got, c["expected_value"]):
                failures.append((cid, f"mismatch: got={repr(got)[:60]} expected={repr(c['expected_value'])[:60]}"))
        else:
            try:
                parse(text)
            except JSONParseError:
                continue
            except Exception as e:
                failures.append((cid, f"malformed wrong exception {type(e).__name__}: {str(e)[:60]}"))
                continue
            failures.append((cid, f"malformed accepted: {text[:30]!r}"))

    rng_seed = int(cfg.get("seed", 0)) ^ int(time.time_ns() & 0xFFFF_FFFF)
    rand_cases = _gen_random_tests(rng_seed)
    rand_failures = []
    for i, (text, expected) in enumerate(rand_cases):
        if time.monotonic() - started > WHOLE_CORRECTNESS_TIMEOUT_S:
            rand_failures.append((f"rand_{i:03d}", "global timeout"))
            break
        try:
            got = parse(text)
        except Exception as e:
            rand_failures.append((f"rand_{i:03d}", f"raised on valid: {type(e).__name__}"))
            continue
        if not _equal(got, expected):
            rand_failures.append((f"rand_{i:03d}", f"mismatch on input len={len(text)}"))

    total = len(cases) + len(rand_cases)
    passed = total - len(failures) - len(rand_failures)
    elapsed = time.monotonic() - started
    metric = 0.0 if (failures == [] and rand_failures == []) else 1.0
    return {
        "status": "ok",
        "metric": metric,
        "metric_components": {
            "passed": passed,
            "total": total,
            "fixed_failures": failures[:20],
            "random_failures": rand_failures[:20],
        },
        "wall_clock_seconds": elapsed,
        "metadata": {
            "verdict": "pass" if metric == 0.0 else "fail",
            "passed": passed,
            "total": total,
        },
    }


def run_performance(cfg: dict) -> dict:
    mod, err = _load_candidate()
    if err is not None:
        return {
            "status": "error",
            "message": f"candidate failed to load: {err[:200]}",
        }

    parse = mod.parse
    JSONParseError = mod.JSONParseError

    cases = _load_corpus()
    inputs = [c["input"] for c in cases]

    # Warm up once (don't time it). This stabilizes any one-time imports
    # the candidate does on first call.
    for s in inputs:
        try:
            parse(s)
        except JSONParseError:
            pass
        except Exception:
            pass

    # Time the parse over all 200 inputs. gc disabled around the timed window.
    gc.disable()
    try:
        gc.collect()
        t0 = time.perf_counter()
        for s in inputs:
            try:
                parse(s)
            except JSONParseError:
                pass
            except Exception:
                # An unexpected exception during perf eval is a correctness violation
                # — but correctness is gated separately. Treat as a hard failure.
                return {
                    "status": "error",
                    "message": f"candidate raised unexpected exception during perf eval: {traceback.format_exc()[:300]}",
                }
        elapsed = time.perf_counter() - t0
    finally:
        gc.enable()

    return {
        "status": "ok",
        "metric": elapsed,
        "metric_components": {"corpus_size": len(inputs), "elapsed_seconds": elapsed},
        "wall_clock_seconds": elapsed,
        "metadata": {"corpus_path": str(CORPUS_PATH), "n_inputs": len(inputs)},
    }


ENTRY_POINTS = {
    "correctness": run_correctness,
    "performance": run_performance,
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--entry", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    fn = ENTRY_POINTS.get(args.entry)
    if fn is None:
        Path(args.output).write_text(
            json.dumps({"status": "error", "message": f"unknown entry point {args.entry}"})
        )
        return 1

    cfg = json.loads(Path(args.config).read_text())
    try:
        result = fn(cfg)
    except Exception:
        result = {
            "status": "error",
            "message": "bench_runner crashed:\n" + traceback.format_exc()[:1000],
        }
    Path(args.output).write_text(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
