"""Turns everything the console knows into one verdict, and the reasons behind it.

A dashboard that only lists numbers makes the reader do the judging. This does
the judging, and shows its working: every concern names what is wrong, how to
see it, and how bad it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.catalog import Catalog
from ..core.config import Config
from ..presentation import language
from ..presentation.language import ATTENTION, OK, PROBLEM, UNKNOWN
from ..presentation.text import plural, verb
from ..record.store import Run
from .metrics import Snapshot

# Re-exported: these are the language module's, and every reader of a verdict
# has always imported them from here.
__all__ = ["ATTENTION", "OK", "PROBLEM", "UNKNOWN", "Concern", "Health", "assess"]

_RANK = {OK: 0, UNKNOWN: 1, ATTENTION: 2, PROBLEM: 3}

RECENT_RUNS = 10


# What a front end could do about a concern, named rather than wired: this
# layer knows no front end, so it says which remedy applies and each front end
# decides whether it has one. A concern with no remedy carries an empty string,
# and nothing invents a button for it.
CHOOSE_ENVIRONMENTS = "choose-environments"
OPEN_CONFIG = "open-config"
OPEN_RUNS = "open-runs"
CHECK = "check"

REMEDY_LABELS = {
    CHOOSE_ENVIRONMENTS: "Manage environments",
    OPEN_CONFIG: "Open the configuration",
    OPEN_RUNS: "See the run",
    CHECK: "Check this control plane",
}


@dataclass(frozen=True)
class Concern:
    level: str
    title: str
    detail: str = ""
    hint: str = ""
    remedy: str = ""

    @property
    def remedy_label(self) -> str:
        return REMEDY_LABELS.get(self.remedy, "")


@dataclass
class Health:
    level: str = OK
    headline: str = "Everything looks healthy"
    concerns: list[Concern] = field(default_factory=list)
    # How much of what this console is meant to report it cannot, said once at
    # the top rather than discovered by reading every card.
    unmeasured: int = 0
    measurable: int = 0

    @property
    def status(self) -> str:
        """The one word the status card leads with."""
        return language.VERDICT[self.level].name

    @property
    def cause(self) -> str:
        """The thing that decided the verdict, or an empty string when nothing did."""
        acting = self.problems + self.attention
        return acting[0].title if acting else ""

    @property
    def impact(self) -> str:
        """What is not being reported because of it."""
        if not self.unmeasured:
            return ""
        return (
            f"{self.unmeasured} of {self.measurable} measures and objectives "
            f"{verb(self.unmeasured, 'is')} waiting on a source"
        )

    @property
    def problems(self) -> list[Concern]:
        return [c for c in self.concerns if c.level == PROBLEM]

    @property
    def attention(self) -> list[Concern]:
        return [c for c in self.concerns if c.level == ATTENTION]

    @property
    def unknowns(self) -> list[Concern]:
        return [c for c in self.concerns if c.level == UNKNOWN]


def _worst(levels: list[str]) -> str:
    return max(levels, key=lambda level: _RANK[level], default=OK)


def _failed_runs(runs: list[Run]) -> list[Run]:
    finished = [r for r in runs if r.state in ("succeeded", "failed")][:RECENT_RUNS]
    return [r for r in finished if r.state == "failed"]


def assess(
    *,
    catalog: Catalog,
    config: Config,
    snapshot: Snapshot,
    runs: list[Run],
) -> Health:
    """Judges the estate, and says what it could not judge."""
    concerns: list[Concern] = []

    failed = _failed_runs(runs)
    if failed:
        last = failed[0]
        concerns.append(
            Concern(
                PROBLEM if len(failed) > 1 else ATTENTION,
                f"{len(failed)} of the last {min(len(runs), RECENT_RUNS)} runs failed"
                if len(failed) > 1
                else f"The last run of {last.name} failed",
                f"most recently {last.name} on {last.environment}, exit {last.exit_code}",
                "The failing task is in the run's own output.",
                remedy=OPEN_RUNS,
            )
        )

    breaching = [s for s in snapshot.slos if s.status == "breach"]
    for slo in breaching:
        concerns.append(
            Concern(
                PROBLEM,
                f"{slo.label} is below target",
                f"{slo.value} against {slo.target} over {slo.window}",
            )
        )

    unusable = [e for e in catalog.environments if not e.usable]
    if unusable:
        concerns.append(
            Concern(
                ATTENTION,
                f"{plural(len(unusable), 'environment')} cannot be used",
                ", ".join(f"{e.name}: {e.reason}" for e in unusable),
                "Restore what it is missing, or take it out of the control plane. "
                "This console cannot supply an inventory.",
                remedy=CHOOSE_ENVIRONMENTS,
            )
        )

    if not config.allow_environments:
        concerns.append(
            Concern(
                UNKNOWN,
                "Read-only: nothing can be launched",
                "No environment has been chosen for this console yet.",
                "Nothing is chosen for you, because that is a decision about production.",
                remedy=CHOOSE_ENVIRONMENTS,
            )
        )

    # What has no source is counted, not listed: every card and every objective
    # row already says what it is short of, and repeating that in a section of
    # its own was the same sentence three times on one page.
    blind = [m for m in snapshot.measures if not m.has_data]
    dark = [s for s in snapshot.slos if not s.has_data]

    level = _worst([c.level for c in concerns])
    measurable = len(snapshot.measures) + len(snapshot.slos)
    unmeasured = len(blind) + len(dark)
    return Health(
        level=level,
        headline=_headline(level, concerns, runs),
        concerns=concerns,
        unmeasured=unmeasured,
        measurable=measurable,
    )


def _headline(level: str, concerns: list[Concern], runs: list[Run]) -> str:
    if level == PROBLEM:
        first = next(c for c in concerns if c.level == PROBLEM)
        return first.title
    if level == ATTENTION:
        first = next(c for c in concerns if c.level == ATTENTION)
        return first.title
    if level == UNKNOWN:
        return "Healthy so far as it can be seen"
    if not runs:
        return "Nothing has run through this console yet"
    return "Everything looks healthy"
