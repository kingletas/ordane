"""What each environment is in, in the ramp's four words rather than a flag.

The catalogue says whether an environment can be used and whether it has been
allowed; the history says what happened the last time anything ran there. This
puts the two together once, so the strip on Overview and the Environments
screen cannot disagree about the same environment.

Nothing that is only unconfigured is ever `degraded` or `failed`. Not being set
up yet is `waiting`, which is blue.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.catalog import Environment
from ..presentation.text import since, took
from ..record.store import Run
from .density import DEGRADED_STATES, outcome

READY = "ready"
WAITING = "waiting"
DEGRADED = "degraded"
FAILED = "failed"


@dataclass(frozen=True)
class Standing:
    """One environment, judged."""

    name: str
    state: str
    word: str
    fix: str = ""
    hosts: int | None = None
    inventory: str = ""
    reason: str = ""
    allowed: bool = True
    usable: bool = True
    last: Run | None = None
    changed: int = 0
    tags: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.state == READY

    @property
    def host_count(self) -> str:
        """Never a zero that means `not asked`: an unknown count is a dash."""
        return "—" if self.hosts is None else str(self.hosts)

    @property
    def when(self) -> str:
        if self.last is None:
            return "never"
        elapsed = since(self.last.started)
        return _short(elapsed) if elapsed is not None else "unknown"

    @property
    def changed_text(self) -> str:
        return "—" if self.last is None else str(self.changed)

    @property
    def facts(self) -> list[tuple[str, str]]:
        """The three a tile prints: hosts, when it last ran, what it had to change."""
        return [
            (self.host_count, "hosts"),
            (self.when, "last run"),
            (self.changed_text, "changed"),
        ]


def standings(
    *,
    environments: list[Environment],
    runs: list[Run],
    hosts: dict[str, int] | None = None,
) -> list[Standing]:
    """One `Standing` per declared environment, in the order the repository declares."""
    counted = hosts or {}
    return [_judge(one, runs, counted.get(one.name)) for one in environments]


def _judge(environment: Environment, runs: list[Run], hosts: int | None) -> Standing:
    last = next((run for run in runs if run.environment == environment.name), None)
    changed = last.result.changed if last is not None else 0

    if not environment.usable:
        return Standing(
            name=environment.name,
            state=WAITING,
            word=_waiting_word(environment.reason),
            fix="Point it at a host source",
            hosts=hosts,
            inventory=environment.inventory,
            reason=environment.reason,
            allowed=environment.allowed,
            usable=False,
            last=last,
            changed=changed,
            tags=_tags(environment, last),
        )

    if not environment.allowed:
        return Standing(
            name=environment.name,
            state=WAITING,
            word="Not chosen yet",
            fix="Allow it and runs from here can reach it",
            hosts=hosts,
            inventory=environment.inventory,
            allowed=False,
            last=last,
            changed=changed,
            tags=_tags(environment, last),
        )

    if last is not None and outcome(last) in DEGRADED_STATES:
        return Standing(
            name=environment.name,
            state=DEGRADED if outcome(last) != "fail" else FAILED,
            word=(
                "Last run did not match" if outcome(last) != "fail" else f"{last.name} failed here"
            ),
            hosts=hosts,
            inventory=environment.inventory,
            last=last,
            changed=changed,
            tags=_tags(environment, last),
        )

    return Standing(
        name=environment.name,
        state=READY,
        word="Ready",
        hosts=hosts,
        inventory=environment.inventory,
        last=last,
        changed=changed,
        tags=_tags(environment, last),
    )


def _waiting_word(reason: str) -> str:
    """The reason as a state, so a tile says what it is waiting on rather than why."""
    lowered = (reason or "").lower()
    if "inventory" in lowered:
        return "Waiting on an inventory"
    return f"Waiting: {reason}" if reason else "Waiting on you"


def _tags(environment: Environment, last: Run | None) -> list[str]:
    """The short facts a row prints beside the name, and only ones that are known."""
    found: list[str] = []
    if environment.inventory:
        found.append(environment.inventory)
    if last is not None:
        result = last.result
        if result.hosts:
            found.append(f"{len(result.hosts)} answered")
        if result.unreachable_hosts:
            found.append(f"{len(result.unreachable_hosts)} did not answer")
        if last.duration_s:
            found.append(f"last took {took(last.duration_s)}")
    return found


def _short(seconds: float) -> str:
    """`2 min`, `3 h`, `4 days`: a tile has room for a figure and a unit."""
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h"
    days = int(seconds // 86400)
    return f"{days} day" if days == 1 else f"{days} days"
