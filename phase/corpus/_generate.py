"""Generate the fixed JSON parser corpus deterministically.

Run once to produce inputs.jsonl and corpus.sha256. The bench manifest pins
the resulting hash; subsequent runs verify the corpus has not drifted.

200 cases total:
  60 shallow valid     (small objects/arrays, mixed primitive types)
  40 deep valid        (5-15 levels of nesting, small breadth)
  40 wide valid        (shallow but 100-500 elements)
  30 edge valid        (unicode, scientific notation, surrogates, empty containers)
  30 malformed         (missing brackets, trailing commas, unquoted keys, etc.)

Each line in inputs.jsonl is a JSON object:
  {"id": "...", "input": "...", "expects": "valid"|"malformed",
   "category": "shallow"|"deep"|"wide"|"edge"|"malformed",
   "expected_value": <parsed value> | null}
"""
from __future__ import annotations

import hashlib
import json
import random
import string
from pathlib import Path
from typing import Any

CORPUS_PATH = Path(__file__).parent / "inputs.jsonl"
HASH_PATH = Path(__file__).parent / "corpus.sha256"


def _rand_string(rng: random.Random, max_len: int = 12) -> str:
    n = rng.randint(1, max_len)
    chars = string.ascii_letters + string.digits + " _-."
    return "".join(rng.choice(chars) for _ in range(n))


def _rand_primitive(rng: random.Random) -> Any:
    kind = rng.choice(["str", "int", "float", "bool", "null"])
    if kind == "str":
        return _rand_string(rng)
    if kind == "int":
        return rng.randint(-10_000, 10_000)
    if kind == "float":
        return round(rng.uniform(-1000.0, 1000.0), 4)
    if kind == "bool":
        return rng.choice([True, False])
    return None


def _shallow_value(rng: random.Random) -> Any:
    kind = rng.choice(["obj", "arr", "prim"])
    if kind == "prim":
        return _rand_primitive(rng)
    n = rng.randint(2, 8)
    if kind == "obj":
        return {_rand_string(rng): _rand_primitive(rng) for _ in range(n)}
    return [_rand_primitive(rng) for _ in range(n)]


def _deep_value(rng: random.Random, depth: int) -> Any:
    if depth <= 0:
        return _rand_primitive(rng)
    kind = rng.choice(["obj", "arr"])
    if kind == "obj":
        return {_rand_string(rng): _deep_value(rng, depth - 1)}
    return [_deep_value(rng, depth - 1)]


def _wide_value(rng: random.Random, n: int) -> Any:
    kind = rng.choice(["obj", "arr"])
    if kind == "obj":
        return {f"k{i}_{_rand_string(rng, 4)}": _rand_primitive(rng) for i in range(n)}
    return [_rand_primitive(rng) for _ in range(n)]


_EDGE_INPUTS: list[tuple[str, Any]] = [
    ('"\\u00e9"', "é"),
    ('"\\uD83D\\uDE00"', "😀"),
    ('"caf\\u00e9 \\t tab"', "café \t tab"),
    ('1e10', 10000000000.0),
    ('1.5E-3', 0.0015),
    ('-0', 0),
    ('-0.0', -0.0),
    ('0', 0),
    ('{}', {}),
    ('[]', []),
    ('  []  ', []),
    ('"\\\\\\""', '\\"'),
    ('"abc\\u0041xyz"', "abcAxyz"),
    ('"\\b\\f\\n\\r\\t"', "\b\f\n\r\t"),
    ('"\\/"', "/"),
    ('123456789012345', 123456789012345),
    ('-99999.99999', -99999.99999),
    ('"' + "x" * 500 + '"', "x" * 500),
    ('{"a":[]}', {"a": []}),
    ('{"":""}', {"": ""}),
    ('[null, true, false]', [None, True, False]),
    ('[[[[[[1]]]]]]', [[[[[[1]]]]]]),
    ('{"k": 1.0e2}', {"k": 100.0}),
    ('{"k": -1.5e-2}', {"k": -0.015}),
    ('"line1\\nline2"', "line1\nline2"),
    ('{"a":1,"b":2,"c":3}', {"a": 1, "b": 2, "c": 3}),
    ('[1,"two",3.14,true,null]', [1, "two", 3.14, True, None]),
    ('{"nested":{"inner":[1,2,3]}}', {"nested": {"inner": [1, 2, 3]}}),
    ('"emoji \\uD83D\\uDC4B done"', "emoji \U0001F44B done"),
    ('  {"k":\t"v"\n}  ', {"k": "v"}),
]


_MALFORMED_INPUTS: list[str] = [
    '{',
    '}',
    '[',
    ']',
    '{"a":}',
    '{"a":1,}',
    '[1,2,]',
    '{a:1}',
    '{"a":1,"b"}',
    '"unterminated',
    '{"a":"unterminated}',
    'tru',
    'fals',
    'nul',
    '+1',
    '{"":}',
    '"\\u123"',
    '"\\x"',
    '"\\u00G0"',
    '01',
    '.5',
    '-',
    '--1',
    '1.',
    '1e',
    '{"a":1} extra',
    '{"a":[1,2}',
    '[{"a":1]',
    '{"k":\n}',
    '{1:1}',
]
# count: 30 entries above



def _gen_shallow(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        v = _shallow_value(rng)
        s = json.dumps(v, ensure_ascii=False, sort_keys=True)
        out.append({
            "id": f"shallow_{i:03d}",
            "input": s,
            "expects": "valid",
            "category": "shallow",
            "expected_value": v,
        })
    return out


def _gen_deep(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        depth = rng.randint(5, 15)
        v = _deep_value(rng, depth)
        s = json.dumps(v, ensure_ascii=False, sort_keys=True)
        out.append({
            "id": f"deep_{i:03d}",
            "input": s,
            "expects": "valid",
            "category": "deep",
            "expected_value": v,
        })
    return out


def _gen_wide(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        size = rng.randint(100, 500)
        v = _wide_value(rng, size)
        s = json.dumps(v, ensure_ascii=False, sort_keys=True)
        out.append({
            "id": f"wide_{i:03d}",
            "input": s,
            "expects": "valid",
            "category": "wide",
            "expected_value": v,
        })
    return out


def _gen_edge(rng: random.Random, n: int) -> list[dict]:
    out = []
    chosen = list(_EDGE_INPUTS)
    while len(chosen) < n:
        chosen.append(rng.choice(_EDGE_INPUTS))
    chosen = chosen[:n]
    for i, (raw, val) in enumerate(chosen):
        out.append({
            "id": f"edge_{i:03d}",
            "input": raw,
            "expects": "valid",
            "category": "edge",
            "expected_value": val,
        })
    return out


def _gen_malformed() -> list[dict]:
    out = []
    for i, raw in enumerate(_MALFORMED_INPUTS):
        out.append({
            "id": f"malformed_{i:03d}",
            "input": raw,
            "expects": "malformed",
            "category": "malformed",
            "expected_value": None,
        })
    return out


def generate(seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    cases = []
    cases.extend(_gen_shallow(rng, 60))
    cases.extend(_gen_deep(rng, 40))
    cases.extend(_gen_wide(rng, 40))
    cases.extend(_gen_edge(rng, 30))
    cases.extend(_gen_malformed())
    assert len(cases) == 200, f"expected 200, got {len(cases)}"
    return cases


def write(cases: list[dict], path: Path) -> str:
    lines = [json.dumps(c, ensure_ascii=False, sort_keys=True) for c in cases]
    blob = ("\n".join(lines) + "\n").encode("utf-8")
    path.write_bytes(blob)
    return "sha256:" + hashlib.sha256(blob).hexdigest()


if __name__ == "__main__":
    cases = generate(seed=42)
    h = write(cases, CORPUS_PATH)
    HASH_PATH.write_text(h + "\n")
    print(f"wrote {len(cases)} cases to {CORPUS_PATH}")
    print(f"hash: {h}")
