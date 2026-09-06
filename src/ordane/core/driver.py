"""What actually runs a target: `make`, or `ansible-playbook` itself.

A control plane wrapped in a Makefile is one shape; a folder of playbooks and
an inventory is another, and it is the commoner one. Neither has to change to
be driven from here: everything this console needs that Ansible does not
express lives in its own file, and the playbooks are read, never written.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAKE = "make"
ANSIBLE = "ansible"


@dataclass(frozen=True)
class Driver:
    key: str
    name: str
    executable: str
    surface: str
    reason: str


DRIVERS = {
    MAKE: Driver(
        key=MAKE,
        name="make",
        executable="make",
        surface="the targets `make help` prints, or the `## description` comments",
        reason="this repository has a Makefile",
    ),
    ANSIBLE: Driver(
        key=ANSIBLE,
        name="ansible-playbook",
        executable="ansible-playbook",
        surface="the playbooks on disk, named by the first play in each",
        reason="this repository has playbooks and no Makefile",
    ),
}

# What the ansible driver runs, unless the config names something else: a
# repository that wraps ansible-playbook in a script of its own.
DEFAULT_ANSIBLE_COMMAND = ["ansible-playbook"]

# Where a playbook lives, when the config does not say. Deliberately shallow:
# a glob that walks the whole tree finds every role's task file as well.
DEFAULT_PLAYBOOK_GLOBS = [
    "playbooks/*.yml",
    "playbooks/*.yaml",
    "actions/*.yml",
    "*.yml",
    "*.yaml",
]


def choose(repo: Path, declared: str = "") -> str:
    """Which driver this repository needs, unless the config already said.

    A Makefile wins where there is one: a repository that has both has gone to
    the trouble of wrapping its playbooks, and the wrapper is what its own
    people run.
    """
    if declared in DRIVERS:
        return declared
    if (repo / "Makefile").is_file() or (repo / "makefile").is_file():
        return MAKE
    return ANSIBLE


def of(key: str) -> Driver:
    return DRIVERS.get(key, DRIVERS[MAKE])


def playbooks_in(repo: Path) -> list[Path]:
    """Every file the default globs call a playbook, without reading any of them."""
    found: list[Path] = []
    for pattern in DEFAULT_PLAYBOOK_GLOBS:
        found += [path for path in sorted(repo.glob(pattern)) if path.is_file()]
    return found


def drivable(repo: Path) -> bool:
    """Whether there is anything here to drive at all.

    A Makefile or a playbook. Neither has to be written for this console: the
    question is only whether the folder is a control plane or a folder.
    """
    return (
        (repo / "Makefile").is_file() or (repo / "makefile").is_file() or bool(playbooks_in(repo))
    )
