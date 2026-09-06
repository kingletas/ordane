"""Remembers which control planes have been driven, most recent first.

A desktop entry has nowhere to type `--repo`, so an application that requires
one cannot be started from a launcher at all. This is the smallest thing that
fixes that, and once the list exists, the menu can offer the others.
"""

from __future__ import annotations

from pathlib import Path

FILE_NAME = "recent-repositories"

# Enough to cover the control planes one person actually moves between, and
# short enough that the menu stays a menu.
LIMIT = 6


def remember(state_dir: Path, repo: Path) -> None:
    """Puts a repository at the top of the list.

    Never raises: a state directory that cannot be written is not a reason to
    refuse to open a repository.
    """
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        kept = [str(repo)] + [str(p) for p in _read(state_dir) if p != repo]
        (state_dir / FILE_NAME).write_text("\n".join(kept[:LIMIT]) + "\n", encoding="utf-8")
    except OSError:
        return


def remembered(state_dir: Path) -> list[Path]:
    """Every remembered repository that is still one, most recent first."""
    return [path for path in _read(state_dir) if is_a_control_plane(path)]


def last(state_dir: Path) -> Path | None:
    """The one to reopen when no repository was named."""
    found = remembered(state_dir)
    return found[0] if found else None


def forget(state_dir: Path, repo: Path) -> None:
    """Drops one entry, for a repository that has moved or been deleted."""
    try:
        kept = [str(path) for path in _read(state_dir) if path != repo]
        (state_dir / FILE_NAME).write_text("\n".join(kept) + "\n", encoding="utf-8")
    except OSError:
        return


def is_a_control_plane(path: Path) -> bool:
    """Whether there is anything here to drive: a Makefile, or playbooks."""
    from . import driver

    return bool(path.name) and path.is_dir() and driver.drivable(path)


def _read(state_dir: Path) -> list[Path]:
    try:
        text = (state_dir / FILE_NAME).read_text(encoding="utf-8")
    except OSError:
        return []
    seen: list[Path] = []
    for line in text.splitlines():
        line = line.strip()
        if line and Path(line) not in seen:
            seen.append(Path(line))
    return seen
