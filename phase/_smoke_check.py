"""Quick standalone smoke check for the naive parser:
- runs the candidate against the fixed corpus
- compares structurally to expected_value
- reports any failures
- times the candidate vs json.loads on the valid subset
"""
from __future__ import annotations

import gc
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "target"))
from json_parser import parse, JSONParseError  # noqa: E402

CORPUS = Path(__file__).parent / "corpus" / "inputs.jsonl"


def equal(a, b) -> bool:
    if type(a) is not type(b):
        if isinstance(a, float) and isinstance(b, int):
            return float(b) == a
        if isinstance(a, int) and isinstance(b, float):
            return float(a) == b
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, float):
        if a != a and b != b:
            return True
        return a == b
    return a == b


def main() -> int:
    cases = [json.loads(line) for line in CORPUS.read_text().splitlines() if line]
    valid = [c for c in cases if c["expects"] == "valid"]
    malformed = [c for c in cases if c["expects"] == "malformed"]

    failures = []
    for c in valid:
        try:
            got = parse(c["input"])
        except Exception as e:
            failures.append((c["id"], "valid raised", repr(e)))
            continue
        if not equal(got, c["expected_value"]):
            failures.append((c["id"], "mismatch", f"got={got!r} expected={c['expected_value']!r}"))
    for c in malformed:
        try:
            parse(c["input"])
            failures.append((c["id"], "malformed accepted", c["input"][:60]))
        except JSONParseError:
            pass
        except Exception as e:
            failures.append((c["id"], "malformed wrong exception", repr(e)))

    print(f"valid: {len(valid)}, malformed: {len(malformed)}, failures: {len(failures)}")
    for f in failures[:20]:
        print(" ", f)

    gc.disable()
    try:
        gc.collect()
        t0 = time.perf_counter()
        for c in cases:
            try:
                parse(c["input"])
            except Exception:
                pass
        cand_t = time.perf_counter() - t0

        gc.collect()
        t0 = time.perf_counter()
        for c in cases:
            try:
                json.loads(c["input"])
            except Exception:
                pass
        ref_t = time.perf_counter() - t0
    finally:
        gc.enable()

    print(f"naive parse all corpus: {cand_t*1000:.2f} ms")
    print(f"json.loads all corpus:  {ref_t*1000:.2f} ms")
    print(f"slowdown factor: {cand_t/ref_t:.1f}x")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
