"""The parts of the configuration this console writes, and nothing else in the file.

The file is mostly comments, and those comments are why the allow list is
empty. Re-serialising the document with a YAML dumper would answer *which
environments are launchable* by deleting the explanation of why none of them
were, so every edit here replaces the lines it owns and leaves the rest byte
for byte.

Three keys are writable: `environments.allow`, `environments.names` and
`slos`. Everything else in the file is the operator's, and this never touches it.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .config import CONFIG_NAME, ConfigError

_ENVIRONMENTS = re.compile(r"^environments\s*:\s*$")
_TOP_LEVEL = re.compile(r"^\S")


def _key(name: str) -> re.Pattern:
    """`allow:` or `names:` at any indentation, inline list or not."""
    return re.compile(rf"^(?P<indent>\s*){re.escape(name)}\s*:(?P<rest>.*)$")


def render(names: list[str]) -> str:
    """The value as this tool writes it: a flow list, or an empty one."""
    return "[" + ", ".join(names) + "]"


def apply(text: str, names: list[str], key: str = "allow") -> str:
    """Returns the file with `environments.<key>` set, every other line unchanged."""
    lines = text.splitlines(keepends=True)
    start = _environments_block(lines)
    if start is None:
        return _append_block(text, names, key)

    pattern = _key(key)
    for index in range(start + 1, len(lines)):
        if _TOP_LEVEL.match(lines[index]) and lines[index].strip():
            break
        match = pattern.match(lines[index].rstrip("\n"))
        if match:
            ending = "\n" if lines[index].endswith("\n") else ""
            replaced = f"{match['indent']}{key}: {render(names)}{ending}"
            return "".join(lines[:index] + [replaced] + _skip_block_items(lines, index + 1))
    # `environments:` exists without this key, so it is added directly beneath
    # the heading where a reader will look for it.
    inserted = f"  {key}: {render(names)}\n"
    return "".join(lines[: start + 1] + [inserted] + lines[start + 1 :])


def _environments_block(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if _ENVIRONMENTS.match(line.rstrip("\n")):
            return index
    return None


def _skip_block_items(lines: list[str], index: int) -> list[str]:
    """Drops the `- name` lines that belonged to a block-style list being replaced."""
    while index < len(lines) and re.match(r"^\s+-\s", lines[index]):
        index += 1
    return lines[index:]


def _append_block(text: str, names: list[str], key: str = "allow") -> str:
    separator = "" if text.endswith("\n") or not text else "\n"
    return f"{text}{separator}\nenvironments:\n  {key}: {render(names)}\n"


def set_slos(text: str, entries: list[dict]) -> str:
    """Replaces the whole `slos:` block, and nothing above or below it.

    Objectives are a list of mappings rather than a line, so the block is
    rewritten entire. Everything outside it: including the comments that say
    why an objective is unmeasurable: is untouched.
    """
    rendered = _render_slos(entries)
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if re.match(r"^slos\s*:\s*$", line.rstrip("\n")):
            after = _skip_indented(lines, index + 1)
            return "".join(lines[:index] + [rendered] + lines[after:])
    separator = "" if text.endswith("\n") or not text else "\n"
    return f"{text}{separator}\n{rendered}"


def _render_slos(entries: list[dict]) -> str:
    if not entries:
        return "slos: []\n"
    out = ["slos:\n"]
    for entry in entries:
        first = True
        for name, value in entry.items():
            if value in (None, "", []):
                continue
            lead = "  - " if first else "    "
            first = False
            out.append(f"{lead}{name}: {_scalar(value)}\n")
    return "".join(out)


def _scalar(value) -> str:
    """A YAML scalar this tool is prepared to write: a list, or a quoted string."""
    if isinstance(value, list):
        return render([str(item) for item in value])
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _skip_indented(lines: list[str], index: int) -> int:
    """The first line at column zero after a block, blank lines included in it."""
    last = index
    while index < len(lines):
        line = lines[index]
        if line.strip() and not line[0].isspace():
            break
        if line.strip():
            last = index + 1
        index += 1
    return max(last, index) if index >= len(lines) else last


def write(repo: Path, names: list[str], key: str = "allow") -> Path:
    """Writes the new list, having proved the result still parses.

    A configuration file that cannot be read is a console that cannot start, so
    the replacement is parsed before it replaces anything.
    """
    path = repo / CONFIG_NAME
    original = path.read_text(encoding="utf-8") if path.is_file() else ""
    updated = apply(original, names, key)
    try:
        parsed = yaml.safe_load(updated) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"the edit would make {path.name} unreadable: {exc}") from exc
    written = [str(n) for n in ((parsed.get("environments") or {}).get(key) or [])]
    if written != list(names):
        raise ConfigError(
            f"the edit did not take: {path.name} would still say {written or 'nothing'}"
        )
    path.write_text(updated, encoding="utf-8")
    return path


def write_slos(repo: Path, entries: list[dict]) -> Path:
    """Writes the objectives, having proved the result parses back to them."""
    path = repo / CONFIG_NAME
    original = path.read_text(encoding="utf-8") if path.is_file() else ""
    updated = set_slos(original, entries)
    try:
        parsed = yaml.safe_load(updated) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"the edit would make {path.name} unreadable: {exc}") from exc
    if len(parsed.get("slos") or []) != len(entries):
        raise ConfigError(f"the edit did not take: {path.name} would hold different objectives")
    path.write_text(updated, encoding="utf-8")
    return path
