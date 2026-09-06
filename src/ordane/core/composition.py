"""What a playbook pulls in, and how much of that is decided at run time.

Ansible already composes, through roles and `import_*` and `include_*`. This
reads that rather than building a second mechanism on top of it.

The distinction worth drawing is static against dynamic: an `import_` is
resolved before the run starts, so a preview can be sure of it, and an
`include_` is resolved while the run goes, so a preview is a guess about it.

It reads what the file names. It does not resolve a variable, evaluate a `when:`
or follow an import into the file it names, because a listing that pretended to
would be a worse guess than an honest one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# `ansible.builtin.import_tasks: tasks/x.yml`, and the short form. `include_vars`
# is deliberately absent: variables are not a step, and listing them among the
# tasks would make a playbook look like it does more than it does.
_PULLS = re.compile(
    r"^\s*-?\s*(?:ansible\.builtin\.)?(?P<how>import_playbook|import_tasks|import_role"
    r"|include_tasks|include_role)\s*:\s*(?P<what>\S.*?)?\s*$"
)
_ROLES = re.compile(r"^(?P<indent>\s*)roles\s*:\s*$")
_ROLE_ENTRY = re.compile(r"^\s*-\s*(?:\{\s*role\s*:\s*)?(?P<name>[A-Za-z0-9_./-]+)")
# `include_role:` and `import_tasks:` are often written with the name on the
# next line, as `name:` for a role and `file:` for a task file.
_NAME_KEY = re.compile(r"^\s*(?:name|role|file)\s*:\s*(?P<name>\S+)")

# Anything a run decides for itself. A listing that resolved these would be
# inventing the answer.
_VARIABLE = re.compile(r"\{\{.*?\}\}")

STATIC = ("import_playbook", "import_tasks", "import_role", "role")

KIND = {
    "import_playbook": "playbook",
    "import_tasks": "tasks",
    "include_tasks": "tasks",
    "import_role": "role",
    "include_role": "role",
    "role": "role",
}


@dataclass(frozen=True)
class Piece:
    """One thing a playbook pulls in, and when that is decided."""

    name: str
    how: str
    times: int = 1

    @property
    def kind(self) -> str:
        return KIND.get(self.how, "tasks")

    @property
    def static(self) -> bool:
        return self.how in STATIC

    @property
    def unresolved(self) -> bool:
        """A name the file does not know either, because it is a variable."""
        return bool(_VARIABLE.search(self.name))


@dataclass(frozen=True)
class Composition:
    """What one playbook is made of, as far as reading it can say."""

    pieces: tuple[Piece, ...] = ()
    error: str = ""

    @property
    def known(self) -> bool:
        return bool(self.pieces) and not self.error

    @property
    def dynamic(self) -> tuple[Piece, ...]:
        return tuple(one for one in self.pieces if not one.static)

    @property
    def unresolved(self) -> tuple[Piece, ...]:
        return tuple(one for one in self.pieces if one.unresolved)

    @property
    def caveat(self) -> str:
        """What a preview of this playbook cannot promise, or nothing.

        A blast radius drawn over a playbook that chooses part of itself at run
        time is a prediction about the part it can see.
        """
        if not self.dynamic:
            return ""
        named = ", ".join(sorted({one.name for one in self.dynamic})[:3])
        more = len({one.name for one in self.dynamic}) - 3
        return (
            f"{len(self.dynamic)} of these are chosen while the run goes: {named}"
            + (f" and {more} more" if more > 0 else "")
            + ". What they do is not known until then."
        )


def read(repo: Path, playbook: str) -> Composition:
    """What the named playbook pulls in. Never raises into a caller."""
    if not playbook:
        return Composition(error="This target does not name a playbook.")
    path = repo / playbook
    try:
        inside = path.resolve()
        inside.relative_to(repo.resolve())
    except (OSError, ValueError):
        return Composition(error="That playbook is outside the control plane.")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return Composition(error=f"{playbook} could not be read.")
    return parse(text)


def parse(text: str) -> Composition:
    """Reads what a playbook names, in the order it names it."""
    counted: dict[tuple[str, str], int] = {}
    order: list[tuple[str, str]] = []

    def remember(how: str, name: str) -> None:
        key = (how, name)
        if key not in counted:
            order.append(key)
        counted[key] = counted.get(key, 0) + 1

    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        pulls = _PULLS.match(line)
        if pulls:
            name = _value(pulls.group("what"))
            if not name:
                name = _named_below(lines, index + 1)
            if name:
                remember(pulls.group("how"), name)
            continue
        block = _ROLES.match(line)
        if block:
            for name in _roles_below(lines, index + 1, len(block.group("indent"))):
                remember("role", name)
    return Composition(pieces=tuple(Piece(name, how, counted[(how, name)]) for how, name in order))


def _value(raw: str | None) -> str:
    """The path or role a line names, or nothing when it is written as a mapping."""
    text = (raw or "").strip().strip("\"'")
    return "" if not text or text.startswith("#") else text


def _named_below(lines: list[str], start: int) -> str:
    """`include_role:` with `name:` under it, which is how a role is usually written."""
    for line in lines[start : start + 4]:
        found = _NAME_KEY.match(line)
        if found:
            return found.group("name").strip("\"'")
        if line.strip() and not line.startswith((" ", "\t")):
            break
    return ""


def _roles_below(lines: list[str], start: int, indent: int) -> list[str]:
    """The entries of a `roles:` block, in both the plain and the mapping form."""
    found: list[str] = []
    for line in lines[start:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip()) <= indent and not line.lstrip().startswith("-"):
            break
        entry = _ROLE_ENTRY.match(line)
        if entry:
            found.append(entry.group("name"))
    return found
