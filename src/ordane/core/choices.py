"""Where a parameter's choice list lives on disk, and how one more joins it.

A choice list read from a directory is a list somebody can add to. The patch
they need is often the one that is not there yet, and a console that can only
offer what already exists sends them back to a terminal to create it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import Param

# What a new entry may be called. Deliberately narrower than a filename: this
# becomes a path, and it is typed by hand.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")

# A patch that carries none of these is almost certainly the wrong paste.
_PATCH_MARKERS = ("diff ", "--- ", "+++ ", "@@ ", "Index: ", "From ", "GIT binary patch")


# How many suggestions are drawn at once. Past this the answer is to type
# another character, not to scroll further.
SHOWN = 12

# A list shorter than this is quicker to look at than to type into.
WORTH_TYPING = 6


def worth_completing(choices: list[str], allow_other: bool, can_add: bool = False) -> bool:
    """Whether this list is better typed into than picked from.

    A list somebody can add to is always typed into: a dropdown has nowhere to
    offer the entry that is not there yet.
    """
    return bool(choices or can_add) and (allow_other or can_add or len(choices) > WORTH_TYPING)


def matches(needle: str, choices: list[str]) -> list[str]:
    """What is left after typing, with what starts that way first."""
    needle = needle.strip().casefold()
    if not needle:
        return list(choices)
    starts = [one for one in choices if one.casefold().startswith(needle)]
    holds = [one for one in choices if needle in one.casefold() and one not in starts]
    return starts + holds


class AddError(ValueError):
    """The new entry was refused, with a reason a person can act on."""


@dataclass(frozen=True)
class Source:
    """A directory a choice list is read from."""

    directory: Path
    suffix: str
    noun: str

    @property
    def writable(self) -> bool:
        return self.directory.is_dir()


def source_for(param: Param, repo: Path) -> Source | None:
    """The directory behind a parameter's choices, when there is one."""
    where = param.choices_from
    if where == "patches":
        return Source(directory=repo / "patches", suffix=".patch", noun="patch")
    if where.startswith("glob:"):
        pattern = where.removeprefix("glob:")
        folder, _, leaf = pattern.rpartition("/")
        if not folder or any(part in {"..", ""} for part in folder.split("/")):
            return None
        suffix = "" if leaf in {"*", ""} else Path(leaf).suffix
        return Source(directory=repo / folder, suffix=suffix, noun=param.name)
    return None


def add(source: Source, name: str, body: str) -> Path:
    """Writes one new entry into the choice list, and returns where it landed.

    Everything here is refused rather than corrected: a name that is not a name,
    a path that leaves the directory, one that is already taken, and a body that
    does not look like what the directory holds.
    """
    name = name.strip()
    if not _NAME.match(name):
        raise AddError(
            "A name may hold letters, digits, dots, dashes and underscores, and starts with "
            "a letter or a digit."
        )
    if not source.writable:
        raise AddError(f"{source.directory} is not a directory this console can write to.")

    path = (source.directory / f"{name}{source.suffix}").resolve()
    if source.directory.resolve() not in path.parents:
        raise AddError("That name would write outside the directory the list is read from.")
    if path.exists():
        raise AddError(f"{path.name} is already there. Pick another name, or use the one on disk.")

    body = body.strip("\n")
    if not body.strip():
        raise AddError("Nothing was pasted.")
    if source.suffix == ".patch" and not any(marker in body for marker in _PATCH_MARKERS):
        raise AddError(
            "That does not look like a patch: none of `diff`, `---`, `@@` or `Index:` is in it."
        )

    path.write_text(body + "\n", encoding="utf-8")
    path.chmod(0o644)
    return path
