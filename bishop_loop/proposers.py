"""Prompts and call functions for Skippy / Bishop / bare-faithful / steelman."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import ollama_client
from .ollama_client import GenerateResult

SKIPPY_MODEL = "qwen3-coder:30b"
# Pilot for follow-up experiment: 1.5B Bishop produced ideas too thin for
# Skippy to implement faithfully (median candidate-similarity ratio 0.99).
# Trying a 4B reasoning model whose ideas are more substantive.
BISHOP_MODEL = "nemotron-3-nano:4b"

SKIPPY_TEMP = 0.7
BISHOP_TEMP = 0.7
SKIPPY_TIMEOUT_S = 180.0
BISHOP_TIMEOUT_S = 120.0  # nemotron uses tokens for chain-of-thought


def _strip_thinking(text: str) -> str:
    """Remove `<think>...</think>` blocks (used by reasoning models like
    nemotron-3-nano). If the closing tag is missing but an opening tag is
    present, also drop everything up to the next newline-then-newline boundary
    or the last 3 sentences, whichever is shorter."""
    import re as _re
    cleaned = _re.sub(r"<think>.*?</think>\s*", "", text, flags=_re.DOTALL)
    # Some completions stop mid-think with only the closing tag present
    # ("...</think>\nfinal answer"). Drop everything up to and including
    # the closing tag.
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[1]
    return cleaned.strip()


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


def skippy_bare_faithful_diff_prompt(source: str, bishop_idea: str) -> str:
    """Diff-mode bare-faithful prompt.

    Asks Skippy to output a unified diff (not a full file rewrite) that
    implements Bishop's idea on top of the current file. This suppresses
    Skippy's tendency to regenerate the whole file from scratch in his own
    style — diff mode requires every change to be a delta against the
    existing source.
    """
    return (
        "You are implementing an optimization idea suggested by another developer.\n\n"
        f"The current implementation is in `json_parser.py`. Here is its full source "
        f"(with line numbers shown only for your reference; do not include them in your diff):\n\n"
        f"```python\n{source}\n```\n\n"
        "The suggestion to implement:\n\n"
        f'"""\n{bishop_idea.strip()}\n"""\n\n'
        "Your task: produce a **unified diff** against the current file that implements\n"
        "EXACTLY this suggestion. Do not improve, substitute, combine with other ideas,\n"
        "or 'fix' the suggestion. Edit only the lines that need to change to implement\n"
        "the suggestion — leave everything else alone.\n\n"
        "Output format: a single ```diff ... ``` fenced block containing standard\n"
        "unified-diff syntax (the format `patch -p1` accepts). The diff must:\n"
        "  - Use `--- a/json_parser.py` and `+++ b/json_parser.py` as the file headers.\n"
        "  - Use `@@ -<old_start>,<old_count> +<new_start>,<new_count> @@` hunk headers.\n"
        "  - Include 3 lines of unchanged context around each change.\n"
        "  - Use single-space-prefix lines for context, `-` for removed lines,\n"
        "    `+` for added lines.\n"
        "  - Be applicable to the source above via `patch -p1` with no fuzz.\n\n"
        "Do not output the full rewritten file. Do not output prose. Just the diff.\n"
        "If the suggestion requires no code change, output a diff with a single\n"
        "no-op hunk that adds a comment explaining why.\n\n"
        "Example shape (your diff must contain real hunks targeting the actual file):\n\n"
        "    ```diff\n"
        "    --- a/json_parser.py\n"
        "    +++ b/json_parser.py\n"
        "    @@ -27,7 +27,7 @@\n"
        "     _WS_CHARS = [\" \", \"\\t\", \"\\n\", \"\\r\"]\n"
        "    -_DIGIT_CHARS = [\"0\", \"1\", \"2\", \"3\", \"4\", \"5\", \"6\", \"7\", \"8\", \"9\"]\n"
        "    +_DIGIT_CHARS = frozenset(\"0123456789\")\n"
        "    ```\n"
    )


def skippy_steelman_diff_prompt(source: str, bishop_idea: str) -> str:
    """Diff-mode steelman prompt: critique + steelman + diff."""
    return (
        "You are evaluating and implementing an optimization idea suggested by another developer.\n\n"
        f"The current implementation is in `json_parser.py`. Here is its full source:\n\n"
        f"```python\n{source}\n```\n\n"
        "The suggestion to consider:\n\n"
        f'"""\n{bishop_idea.strip()}\n"""\n\n'
        "Your task has three parts:\n\n"
        "Part 1 — Critique (2-3 sentences). Explain why this suggestion as stated seems\n"
        "unworkable, suboptimal, or naive. Be specific about the failure modes you anticipate.\n\n"
        "Part 2 — Steelman (2-3 sentences). Propose the strongest version of this suggestion —\n"
        "the steelman that addresses the failure modes you identified. The steelman should\n"
        "preserve the core direction of the original suggestion, not replace it with a\n"
        "different idea entirely.\n\n"
        "Part 3 — Diff. Produce a unified diff against the current `json_parser.py` that\n"
        "implements the Part 2 steelman. Edit only the lines that need to change; leave\n"
        "everything else alone.\n\n"
        "Output format: emit the critique and steelman first, each on its own line\n"
        "prefixed exactly with `CRITIQUE:` and `STEELMAN:` (no code-fence around them).\n"
        "Then a single ```diff ... ``` fenced block containing the unified diff. The diff must:\n"
        "  - Use `--- a/json_parser.py` and `+++ b/json_parser.py` headers.\n"
        "  - Use `@@ -<old_start>,<old_count> +<new_start>,<new_count> @@` hunk headers.\n"
        "  - Include 3 lines of unchanged context around each change.\n"
        "  - Be applicable via `patch -p1` with no fuzz against the source above.\n\n"
        "Do not output the full rewritten file. Do not put the critique/steelman inside\n"
        "the diff block. Do not include explanatory prose between the headers and the diff.\n\n"
        "Example shape (your actual diff must target the real file):\n\n"
        "    CRITIQUE: <your critique>\n"
        "    STEELMAN: <your steelman>\n\n"
        "    ```diff\n"
        "    --- a/json_parser.py\n"
        "    +++ b/json_parser.py\n"
        "    @@ -27,7 +27,7 @@\n"
        "     _WS_CHARS = [\" \", \"\\t\", \"\\n\", \"\\r\"]\n"
        "    -_DIGIT_CHARS = [\"0\", \"1\", \"2\", \"3\", \"4\", \"5\", \"6\", \"7\", \"8\", \"9\"]\n"
        "    +_DIGIT_CHARS = frozenset(\"0123456789\")\n"
        "    ```\n"
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
        "Your task has three parts:\n\n"
        "Part 1 — Critique (2-3 sentences). Explain why this suggestion as stated seems\n"
        "unworkable, suboptimal, or naive. Be specific about the failure modes you anticipate.\n\n"
        "Part 2 — Steelman (2-3 sentences). Propose the strongest version of this suggestion —\n"
        "the steelman that addresses the failure modes you identified. The steelman should\n"
        "preserve the core direction of the original suggestion, not replace it with a\n"
        "different idea entirely.\n\n"
        "Part 3 — Implementation. Produce a complete, working file rewrite of `json_parser.py`\n"
        "that implements the Part 2 steelman. The file must contain real, executable Python\n"
        "code — not prose, not placeholders, not a sketch.\n\n"
        "Output format: a SINGLE ```python ... ``` fenced code block containing the entire\n"
        "file. The first two non-empty comment lines must summarize the critique and the\n"
        "steelman; everything after that must be the real implementation. The harness will\n"
        "import this file and run `parse()` against the corpus, so it must be valid Python\n"
        "with real function bodies.\n\n"
        "Example shape (this shows the structure, not the content — your file must contain a\n"
        "complete, runnable parser, not the shape's prose):\n\n"
        "    ```python\n"
        "    # CRITIQUE: <your critique here>\n"
        "    # STEELMAN: <your steelman here>\n"
        "    from __future__ import annotations\n"
        "    class JSONParseError(ValueError): pass\n"
        "    def parse(text):\n"
        "        # ... your implementation ...\n"
        "        ...\n"
        "    # ... rest of the parser implementation ...\n"
        "    ```\n\n"
        "Do not emit literal placeholder strings such as `<your critique here>`, ellipses,\n"
        "or phrases like `rest of the implementation goes here` — write the actual code.\n\n"
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
    # Nemotron uses chain-of-thought; budget for that plus the final 2-3
    # sentence answer.
    res = ollama_client.generate(
        model=BISHOP_MODEL,
        prompt=prompt,
        seed=seed,
        temperature=temperature if temperature is not None else BISHOP_TEMP,
        num_predict=1024,
        timeout_s=BISHOP_TIMEOUT_S,
    )
    # Strip any reasoning prelude (model-specific; harmless on models that
    # don't emit <think> tags).
    cleaned_text = _strip_thinking(res.text)
    return GenerateResult(
        text=cleaned_text,
        eval_count=res.eval_count,
        eval_duration_ns=res.eval_duration_ns,
        prompt_eval_count=res.prompt_eval_count,
        total_duration_ns=res.total_duration_ns,
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
