"""Minimal HTTP client for Ollama's /api/generate endpoint.

Synchronous calls — concurrency is not needed at this scale (one Skippy call
+ one Bishop call per iteration). Retries on transient HTTP errors.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_HOST = "http://localhost:11434"


@dataclass
class GenerateResult:
    text: str
    eval_count: int
    eval_duration_ns: int
    prompt_eval_count: int
    total_duration_ns: int

    @property
    def total_seconds(self) -> float:
        return self.total_duration_ns / 1e9

    @property
    def total_tokens(self) -> int:
        return self.prompt_eval_count + self.eval_count


def generate(
    *,
    model: str,
    prompt: str,
    seed: int,
    temperature: float = 0.7,
    num_predict: int = 4096,
    timeout_s: float = 180.0,
    host: str = DEFAULT_HOST,
    max_retries: int = 3,
) -> GenerateResult:
    """Call Ollama /api/generate; return the response text and stats.

    Retries transient HTTP errors with exponential backoff. Reraises on
    persistent failure.
    """
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "seed": int(seed),
            "temperature": float(temperature),
            "num_predict": int(num_predict),
        },
    }
    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                f"{host}/api/generate",
                json=payload,
                timeout=timeout_s,
            )
            r.raise_for_status()
            d = r.json()
            return GenerateResult(
                text=d.get("response", ""),
                eval_count=int(d.get("eval_count", 0) or 0),
                eval_duration_ns=int(d.get("eval_duration", 0) or 0),
                prompt_eval_count=int(d.get("prompt_eval_count", 0) or 0),
                total_duration_ns=int(d.get("total_duration", 0) or 0),
            )
        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            if attempt + 1 < max_retries:
                time.sleep(2.0 ** attempt)
                continue
            raise
    raise RuntimeError(f"unreachable: {last_err}")


def extract_python_block(text: str) -> str | None:
    """Return the first ```python ...``` fenced block, or the first ``` block.

    Returns None if no fenced block is found.
    """
    import re

    m = re.search(r"```(?:python|py)\s*\n(.*?)```", text, re.DOTALL)
    if m is not None:
        return m.group(1)
    m = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if m is not None:
        return m.group(1)
    return None
