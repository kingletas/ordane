"""What git says about the control plane, for the one line that reports it.

A deploy launched from a dirty working tree is a deploy nobody can reproduce,
and the branch is the difference between shipping what was reviewed and
shipping what happens to be checked out. Both are cheap to read and neither is
anywhere else in this interface.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import host

# Long enough for a cold cache on a large repository, short enough that a
# hanging git never holds the interface: this runs on every refresh.
TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class Checkout:
    """The state of the working tree, or the fact that there is not one."""

    is_git: bool = False
    branch: str = ""
    commit: str = ""
    dirty: bool = False
    detached: bool = False
    behind: int = 0

    @property
    def summary(self) -> str:
        """`main · clean`, `main · 3 changes · 2 behind`, or nothing outside git."""
        if not self.is_git:
            return ""
        where = "detached HEAD" if self.detached else self.branch or "unknown branch"
        parts = [where, "uncommitted changes" if self.dirty else "clean"]
        if self.behind:
            parts.append(f"{self.behind} behind the remote")
        return " · ".join(parts)


def read(repo: Path) -> Checkout:
    """Reads the checkout. Never raises: this is a status line, not a gate."""
    # No `.git` check: a control plane that lives inside a larger repository is
    # still under version control, and git answers from any subdirectory.
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch is None:
        return Checkout()
    status = _git(repo, "status", "--porcelain")
    return Checkout(
        is_git=True,
        branch="" if branch == "HEAD" else branch,
        commit=_git(repo, "rev-parse", "--short", "HEAD") or "",
        detached=branch == "HEAD",
        dirty=bool(status),
        behind=_behind(repo),
    )


def _behind(repo: Path) -> int:
    """Commits the remote has that this checkout does not, from the last fetch.

    It never fetches: a status line that reaches the network is one that hangs
    a window the first time somebody is on a train.
    """
    counted = _git(repo, "rev-list", "--count", "HEAD..@{upstream}")
    try:
        return int(counted) if counted else 0
    except ValueError:
        return 0


def remote(repo: Path) -> str:
    """The URL git calls `origin`, or an empty string where there is none.

    Many repositories here have no remote at all, which is why nothing may
    depend on this: it is one of three ways a control plane gets its name.
    """
    return _git(repo, "remote", "get-url", "origin") or ""


def _git(repo: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            host.argv(["git", *arguments]),
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None
