"""Reference JSON parser. Frozen — never edited by the candidate.

Thin wrapper around `json.loads` used by the bench runner to determine the
ground truth for both the fixed corpus and the randomized correctness tests.
"""
from __future__ import annotations

import json
from typing import Any


def parse(text: str) -> Any:
    return json.loads(text)
