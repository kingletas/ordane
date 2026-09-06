"""What a control plane is called, portably.

A run used to record the absolute path it came from: `/home/you/control-plane`.
That means nothing on anybody else's machine, and two
people with different checkout paths produce records that look like two
different estates. The scoping that stops one control plane's dashboard judging
another's runs was keyed on that path.

So a control plane has a name. It is declared, or derived from the git remote,
and only as a last resort from the folder: which is the case the doctor warns
about, because two people can easily have two different repositories in folders
of the same name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import repository

DECLARED = "declared"
REMOTE = "remote"
FOLDER = "folder"

WHERE_FROM = {
    DECLARED: "declared in the configuration",
    REMOTE: "derived from the git remote",
    FOLDER: "the name of the folder, which is not portable",
}

# A name that will be written into a shared record and read back by a machine
# that has never seen this checkout.
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")

# `git@host:owner/repo.git` and `https://host/owner/repo.git` both reduce to
# `owner/repo`, so two people who cloned differently agree.
_REMOTE = re.compile(r"^(?:[^@/]+@[^:]+:|[a-z]+://[^/]+/)(?P<path>.+?)(?:\.git)?$")


@dataclass(frozen=True)
class Identity:
    name: str
    source: str

    @property
    def portable(self) -> bool:
        """Whether another machine would arrive at the same name."""
        return self.source in (DECLARED, REMOTE)

    @property
    def where_from(self) -> str:
        return WHERE_FROM[self.source]


def of(repo: Path, declared: str = "") -> Identity:
    """The name this control plane is known by, and where that name came from."""
    if declared and _SAFE.match(declared):
        return Identity(name=declared, source=DECLARED)
    remote = from_remote(repo)
    if remote:
        return Identity(name=remote, source=REMOTE)
    return Identity(name=repo.name or str(repo), source=FOLDER)


def from_remote(repo: Path) -> str:
    """`owner/repo` from whichever remote git calls origin, or an empty string."""
    url = repository.remote(repo)
    if not url:
        return ""
    match = _REMOTE.match(url.strip())
    path = match.group("path") if match else url.strip()
    path = path.strip("/")
    return path if _SAFE.match(path) else ""
