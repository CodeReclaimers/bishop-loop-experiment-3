"""Deliberately slow but correct JSON parser. Editable surface.

This is the starting point for the optimization loop. It is correct against
`json.loads` on the full corpus but is intentionally written in a way that
leaves significant performance on the table:

- Regex patterns recompiled inside hot loops.
- Many small slice/strip/concat allocations per token.
- No batching or caching of any kind.
- Recursive descent with redundant whitespace handling at every level.
- Character-by-character escape decoding via shell-style branching.

The optimization target is wall-clock time to parse the 200-case fixed
corpus. The candidate must keep `parse(text) -> Any` as the public entry
point and must raise `JSONParseError` for malformed inputs.
"""
from __future__ import annotations

import re
from typing import Any


class JSONParseError(ValueError):
    """Raised when the input is not valid JSON."""


def parse(text: str) -> Any:
    if not isinstance(text, str):
        raise JSONParseError("input must be a string")
    pos = _skip_ws(text, 0)
    if pos >= len(text):
        raise JSONParseError("empty input")
    value, pos = _parse_value(text, pos)
    pos = _skip_ws(text, pos)
    if pos != len(text):
        raise JSONParseError(f"trailing content at position {pos}")
    return value


def _skip_ws(text: str, pos: int) -> int:
    # Re-slice the tail string and strip — many small allocations.
    ws_re = re.compile(r"^[ \t\n\r]*")
    tail = text[pos:]
    m = ws_re.match(tail)
    if m is None:
        return pos
    return pos + m.end()


def _parse_value(text: str, pos: int) -> tuple[Any, int]:
    pos = _skip_ws(text, pos)
    if pos >= len(text):
        raise JSONParseError("unexpected end of input")
    # take a single-char slice rather than direct index — extra allocation per call.
    c = text[pos : pos + 1]
    if c == "{":
        return _parse_object(text, pos)
    if c == "[":
        return _parse_array(text, pos)
    if c == '"':
        return _parse_string(text, pos)
    if c == "t" or c == "f":
        return _parse_bool(text, pos)
    if c == "n":
        return _parse_null(text, pos)
    if c == "-" or c.isdigit():
        return _parse_number(text, pos)
    raise JSONParseError(f"unexpected character {c!r} at position {pos}")


def _parse_object(text: str, pos: int) -> tuple[dict, int]:
    open_re = re.compile(r"\{")
    close_re = re.compile(r"\}")
    colon_re = re.compile(r":")
    comma_re = re.compile(r",")
    quote_re = re.compile(r'"')
    if not open_re.match(text, pos):
        raise JSONParseError(f"expected '{{' at {pos}")
    pos += 1
    out: dict = {}
    pos = _skip_ws(text, pos)
    if close_re.match(text, pos):
        return out, pos + 1
    while True:
        pos = _skip_ws(text, pos)
        if pos >= len(text) or not quote_re.match(text, pos):
            raise JSONParseError(f"expected string key at {pos}")
        key, pos = _parse_string(text, pos)
        pos = _skip_ws(text, pos)
        if pos >= len(text) or not colon_re.match(text, pos):
            raise JSONParseError(f"expected ':' at {pos}")
        pos += 1
        pos = _skip_ws(text, pos)
        value, pos = _parse_value(text, pos)
        out = dict(out)  # rebuild dict each iteration for extra allocation
        out[key] = value
        pos = _skip_ws(text, pos)
        if pos >= len(text):
            raise JSONParseError("unterminated object")
        if comma_re.match(text, pos):
            pos += 1
            continue
        if close_re.match(text, pos):
            return out, pos + 1
        raise JSONParseError(f"expected ',' or '}}' at {pos}")


def _parse_array(text: str, pos: int) -> tuple[list, int]:
    open_re = re.compile(r"\[")
    close_re = re.compile(r"\]")
    comma_re = re.compile(r",")
    if not open_re.match(text, pos):
        raise JSONParseError(f"expected '[' at {pos}")
    pos += 1
    out: list = []
    pos = _skip_ws(text, pos)
    if close_re.match(text, pos):
        return out, pos + 1
    while True:
        pos = _skip_ws(text, pos)
        value, pos = _parse_value(text, pos)
        out = out + [value]  # rebuild list each iteration for extra allocation
        pos = _skip_ws(text, pos)
        if pos >= len(text):
            raise JSONParseError("unterminated array")
        if comma_re.match(text, pos):
            pos += 1
            continue
        if close_re.match(text, pos):
            return out, pos + 1
        raise JSONParseError(f"expected ',' or ']' at {pos}")


def _parse_string(text: str, pos: int) -> tuple[str, int]:
    quote_re = re.compile(r'"')
    if not quote_re.match(text, pos):
        raise JSONParseError(f"expected '\"' at {pos}")
    pos += 1
    out = ""
    while pos < len(text):
        c = text[pos : pos + 1]
        if c == '"':
            return out, pos + 1
        if c == "\\":
            pos += 1
            if pos >= len(text):
                raise JSONParseError("unterminated string escape")
            esc = text[pos]
            if esc == '"':
                out = out + '"'
            elif esc == "\\":
                out = out + "\\"
            elif esc == "/":
                out = out + "/"
            elif esc == "b":
                out = out + "\b"
            elif esc == "f":
                out = out + "\f"
            elif esc == "n":
                out = out + "\n"
            elif esc == "r":
                out = out + "\r"
            elif esc == "t":
                out = out + "\t"
            elif esc == "u":
                hex_re = re.compile(r"[0-9a-fA-F]{4}")
                m = hex_re.match(text, pos + 1)
                if m is None:
                    raise JSONParseError(f"bad unicode escape at {pos}")
                cp = int(m.group(0), 16)
                if 0xD800 <= cp <= 0xDBFF:
                    if text[pos + 5 : pos + 7] != "\\u":
                        raise JSONParseError(f"unpaired high surrogate at {pos}")
                    m2 = hex_re.match(text, pos + 7)
                    if m2 is None:
                        raise JSONParseError(f"bad unicode escape at {pos + 7}")
                    cp2 = int(m2.group(0), 16)
                    if not (0xDC00 <= cp2 <= 0xDFFF):
                        raise JSONParseError(f"bad low surrogate at {pos + 7}")
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (cp2 - 0xDC00)
                    out = out + chr(cp)
                    pos += 11
                    continue
                out = out + chr(cp)
                pos += 4
            else:
                raise JSONParseError(f"bad escape \\{esc} at {pos}")
            pos += 1
            continue
        if ord(c) < 0x20:
            raise JSONParseError(f"unescaped control character at {pos}")
        out = out + c
        pos += 1
    raise JSONParseError("unterminated string")


def _parse_bool(text: str, pos: int) -> tuple[bool, int]:
    if text[pos : pos + 4] == "true":
        return True, pos + 4
    if text[pos : pos + 5] == "false":
        return False, pos + 5
    raise JSONParseError(f"bad bool at {pos}")


def _parse_null(text: str, pos: int) -> tuple[None, int]:
    if text[pos : pos + 4] == "null":
        return None, pos + 4
    raise JSONParseError(f"bad null at {pos}")


def _parse_number(text: str, pos: int) -> tuple[float | int, int]:
    num_re = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
    tail = text[pos:]
    m = num_re.match(tail)
    if m is None or m.group(0) == "":
        raise JSONParseError(f"bad number at {pos}")
    s = m.group(0)
    end = pos + m.end()
    if "." in s or "e" in s or "E" in s:
        return float(s), end
    return int(s), end
