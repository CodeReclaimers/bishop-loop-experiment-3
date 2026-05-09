"""Prompts and call functions for Skippy / Bishop / bare-faithful / steelman."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import ollama_client
from .ollama_client import GenerateResult

SKIPPY_MODEL = "qwen3-coder:30b"
BISHOP_MODEL = "qwen2.5-coder:1.5b"

SKIPPY_TEMP = 0.7
BISHOP_TEMP = 0.7
SKIPPY_TIMEOUT_S = 180.0
BISHOP_TIMEOUT_S = 60.0


@dataclass
class IterationHistory:
    promoted: list[str]
    rejected: list[str]
    # Optional: short code excerpts from the last rejected candidates so the
    # next proposer can visually compare against what failed. Stored in
    # newest-first order. Each entry is at most ~30 lines.
    rejected_code_excerpts: list[str] = field(default_factory=list)


def _truncate_source(source: str, max_lines: int = 400) -> str:
    lines = source.splitlines()
    if len(lines) <= max_lines:
        return source
    head = lines[: max_lines // 2]
    tail = lines[-max_lines // 2 :]
    return "\n".join(head) + f"\n# ... {len(lines) - max_lines} lines elided ...\n" + "\n".join(tail)


def _format_history(hist: IterationHistory) -> str:
    promoted = hist.promoted[-5:]
    rejected = hist.rejected[-5:]
    p = "\n".join(f"  - {s}" for s in promoted) if promoted else "  (none yet)"
    r = "\n".join(f"  - {s}" for s in rejected) if rejected else "  (none yet)"
    out = f"Accepted improvements (most recent first):\n{p}\n\nRejected attempts (most recent first):\n{r}"
    excerpts = hist.rejected_code_excerpts[:2]
    if excerpts:
        out += "\n\nExcerpts from the most recent rejected candidates (avoid repeating these mistakes):\n"
        for i, ex in enumerate(excerpts, 1):
            out += f"\n--- rejection {i} ---\n{ex}\n"
    return out


def _common_constraints() -> str:
    return (
        "Constraints:\n"
        "- The function `parse(text: str) -> Any` must remain the public entry point.\n"
        "- A class `JSONParseError(ValueError)` must be defined and raised for malformed inputs.\n"
        "- Pure Python (standard library only). No third-party packages.\n"
        "- Do NOT import the `json` standard library module — it would defeat the optimization\n"
        "  landscape and is statically rejected by the harness.\n"
        "- Output a single ```python ... ``` fenced code block containing the COMPLETE file.\n"
        "  No prose outside the code block.\n"
    )


def skippy_prompt(source: str, hist: IterationHistory) -> str:
    return (
        "You are improving a Python JSON parser to make it faster while keeping it correct.\n\n"
        f"The current implementation is in `json_parser.py`. Here is its full source:\n\n"
        f"```python\n{_truncate_source(source)}\n```\n\n"
        "Recent history:\n"
        f"{_format_history(hist)}\n\n"
        "Your task: produce a complete file rewrite of `json_parser.py` that is faster on a\n"
        "corpus of mixed JSON inputs while passing all correctness tests against the reference\n"
        "(`json.loads`). The corpus contains shallow objects, deep nesting, wide arrays (100-500\n"
        "elements), edge cases (unicode, scientific notation, surrogate pairs), and malformed\n"
        "inputs your parser must reject by raising JSONParseError.\n\n"
        f"{_common_constraints()}"
    )


def bishop_idea_prompt(source: str, hist: IterationHistory) -> str:
    return (
        "You are suggesting an optimization idea for a Python JSON parser.\n\n"
        f"The current implementation is in `json_parser.py`. Here is its full source:\n\n"
        f"```python\n{_truncate_source(source, max_lines=200)}\n```\n\n"
        "Recent ideas already tried:\n"
        f"{_format_history(hist)}\n\n"
        "Your task: in 2-3 sentences, suggest one specific change to try in `json_parser.py`\n"
        "to make it faster while keeping it correct. Do NOT include code. Describe the approach\n"
        "only. Be specific about which part of the code changes and what mechanism makes it faster.\n\n"
        "Output: just the 2-3 sentence suggestion. No preamble. No postamble. No code.\n"
    )


def skippy_bare_faithful_prompt(source: str, bishop_idea: str) -> str:
    return (
        "You are implementing an optimization idea suggested by another developer.\n\n"
        f"The current implementation is in `json_parser.py`. Here is its full source:\n\n"
        f"```python\n{_truncate_source(source)}\n```\n\n"
        "The suggestion to implement:\n\n"
        f'"""\n{bishop_idea.strip()}\n"""\n\n'
        "Your task: produce a complete file rewrite of `json_parser.py` that implements EXACTLY\n"
        "this suggestion. Do not improve, substitute, combine with other ideas, or 'fix' the\n"
        "suggestion. If the suggestion is unclear, make the most direct interpretation possible.\n"
        "The goal is to test whether this specific idea, faithfully implemented, makes the parser\n"
        "faster while keeping it correct.\n\n"
        f"{_common_constraints()}"
    )


def skippy_steelman_prompt(source: str, bishop_idea: str) -> str:
    return (
        "You are evaluating and implementing an optimization idea suggested by another developer.\n\n"
        f"The current implementation is in `json_parser.py`. Here is its full source:\n\n"
        f"```python\n{_truncate_source(source)}\n```\n\n"
        "The suggestion to consider:\n\n"
        f'"""\n{bishop_idea.strip()}\n"""\n\n'
        "Your task has three parts.\n\n"
        "First, in 2-3 sentences, explain why this suggestion as stated seems unworkable,\n"
        "suboptimal, or naive. Be specific about the failure modes you anticipate.\n\n"
        "Second, in 2-3 sentences, propose the strongest version of this suggestion — the\n"
        "steelman that addresses the failure modes you identified. The steelman should preserve\n"
        "the core direction of the original suggestion, not replace it with a different idea\n"
        "entirely.\n\n"
        "Third, produce a complete file rewrite of `json_parser.py` that implements the steelman.\n\n"
        "Output format: first the critique and steelman as comments at the top of the file,\n"
        "then the implementation. Wrap the entire file in a single ```python ... ``` fenced\n"
        "code block. Use this header structure:\n\n"
        "```python\n"
        "# CRITIQUE:\n"
        "# <2-3 sentences about why the suggestion is unworkable as stated>\n"
        "#\n"
        "# STEELMAN:\n"
        "# <2-3 sentences proposing the strongest version>\n\n"
        "<rest of the file implementing the steelman>\n"
        "```\n\n"
        f"{_common_constraints()}"
    )


# ---- model call wrappers ----


def call_skippy(prompt: str, *, seed: int) -> GenerateResult:
    return ollama_client.generate(
        model=SKIPPY_MODEL,
        prompt=prompt,
        seed=seed,
        temperature=SKIPPY_TEMP,
        num_predict=8192,
        timeout_s=SKIPPY_TIMEOUT_S,
    )


def call_bishop(prompt: str, *, seed: int, temperature: float | None = None) -> GenerateResult:
    return ollama_client.generate(
        model=BISHOP_MODEL,
        prompt=prompt,
        seed=seed,
        temperature=temperature if temperature is not None else BISHOP_TEMP,
        num_predict=512,
        timeout_s=BISHOP_TIMEOUT_S,
    )


def extract_critique_steelman(text: str) -> tuple[str | None, str | None]:
    """Pull the CRITIQUE: and STEELMAN: blocks from a steelman code rewrite header."""
    crit = None
    steel = None
    m = re.search(r"#\s*CRITIQUE:\s*\n((?:#.*\n)+)", text)
    if m is not None:
        crit = "\n".join(line.lstrip("# ").rstrip() for line in m.group(1).splitlines())
    m = re.search(r"#\s*STEELMAN:\s*\n((?:#.*\n)+)", text)
    if m is not None:
        steel = "\n".join(line.lstrip("# ").rstrip() for line in m.group(1).splitlines())
    return crit, steel
