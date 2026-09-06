"""Splits Ansible's terminal colour into styled segments.

One parser serves every front end: the desktop app turns a segment into a text
tag, the web page turns it into a span. HTML escaping happens after the split,
so nothing in a playbook's output can inject markup into a page.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_SEQUENCE = re.compile(r"\x1b\[([0-9;]*)m")
_OTHER_ESCAPES = re.compile(
    r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|[\x00-\x08\x0b\x0c\x0e-\x1f]"
)

# Ansible uses the eight basic foreground colours and little else.
_COLOUR = {
    30: "black",
    31: "red",
    32: "green",
    33: "yellow",
    34: "blue",
    35: "magenta",
    36: "cyan",
    37: "white",
    90: "grey",
    91: "red",
    92: "green",
    93: "yellow",
    94: "blue",
    95: "magenta",
    96: "cyan",
    97: "white",
}

RESET = 0
BOLD = 1
DIM = 2


@dataclass(frozen=True)
class Segment:
    """A run of text and the styles in force over it."""

    text: str
    styles: tuple[str, ...] = ()


def _styles(codes: list[int]) -> tuple[str, ...]:
    names = [_COLOUR[c] for c in codes if c in _COLOUR]
    if BOLD in codes:
        names.append("bold")
    if DIM in codes:
        names.append("dim")
    return tuple(names)


def segments(text: str) -> list[Segment]:
    """Splits the text into runs, dropping every escape that is not a colour."""
    out: list[Segment] = []
    active: tuple[str, ...] = ()
    position = 0

    def add(chunk: str) -> None:
        cleaned = _OTHER_ESCAPES.sub("", chunk)
        if cleaned:
            out.append(Segment(cleaned, active))

    for match in _SEQUENCE.finditer(text):
        add(text[position : match.start()])
        position = match.end()

        codes = [int(c) for c in match.group(1).split(";") if c.isdigit()] or [RESET]
        if RESET in codes:
            active = ()
            codes = [c for c in codes if c != RESET]
        found = _styles(codes)
        if found:
            active = tuple(dict.fromkeys(active + found))

    add(text[position:])
    return out


def to_html(text: str) -> str:
    """Escapes the text, then wraps each coloured run in a span."""
    out: list[str] = []
    for segment in segments(text):
        escaped = html.escape(segment.text)
        if segment.styles:
            classes = " ".join(f"a-{s}" for s in segment.styles)
            out.append(f'<span class="{classes}">{escaped}</span>')
        else:
            out.append(escaped)
    return "".join(out)


def strip(text: str) -> str:
    """The same text with every escape removed, for anything that parses rather
    than renders: a `make help` that colours its output is still `make help`."""
    return _OTHER_ESCAPES.sub("", _SEQUENCE.sub("", text))
