"""One sentence saying whether it is safe to act, and one line naming what is not.

This is the hero of the Overview and the only thing on it allowed to be large.
It answers the question the console is opened with — *can I deploy?* — before
any card, table or number is read.

The four states are the ramp's, and the important one is `waiting`: a
repository that has simply not finished being set up is blue, never amber.
Amber and red are for things that ran and went wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.catalog import Catalog
from ..presentation.text import sentence
from .density import FAIL, LIVE, OK, WARN, outcome
from .health import Health
from .setup import CHOOSE_ENVIRONMENTS, Setup

READY = "ready"
WAITING = "waiting"
DEGRADED = "degraded"
FAILED = "failed"

# How many recent runs decide whether something is currently broken. Beyond
# this a failure is history rather than news.
RECENT = 10


@dataclass(frozen=True)
class Verdict:
    """The one sentence, the one line under it, and what that line links to."""

    state: str = READY
    headline: str = ""
    note: str = ""
    remedy: str = ""
    remedy_label: str = ""

    @property
    def actionable(self) -> bool:
        return bool(self.remedy and self.remedy_label)


def decide(
    *,
    catalog: Catalog | None,
    health: Health,
    setup: Setup,
    runs: list,
    error: str = "",
) -> Verdict:
    """Judges once, from what everything else already worked out."""
    if catalog is None:
        return Verdict(
            state=FAILED,
            headline="This repository cannot be read.",
            note=error or "Nothing has been changed and nothing has run.",
            remedy="check",
            remedy_label="See what is wrong",
        )

    launchable = [one.name for one in catalog.launchable_environments]
    failed = [run for run in runs[:RECENT] if outcome(run) == FAIL]
    degraded = [run for run in runs[:RECENT] if outcome(run) == WARN]
    breaching = [concern for concern in health.problems if "below target" in concern.title]

    if failed:
        last = failed[0]
        return Verdict(
            state=FAILED,
            headline=_failed_headline(failed),
            note=f"{last.name} on {last.environment or 'this repository'} is the most "
            f"recent. Its output says which task stopped it.",
            remedy="open-runs",
            remedy_label="Open the run",
        )

    if not launchable:
        return Verdict(
            state=WAITING,
            headline="Nothing can be launched yet.",
            note="No environment has been named, so this repository is read-only. "
            "Nothing is chosen for you, because that is a decision about production.",
            remedy=CHOOSE_ENVIRONMENTS,
            remedy_label="Name an environment",
        )

    if degraded:
        last = degraded[0]
        return Verdict(
            state=DEGRADED,
            headline="The last run did not do what the repository says.",
            note=f"{last.name} on {last.environment} finished, and its recap reports "
            "a host that did not match. Nothing is broken; nothing is confirmed either.",
            remedy="open-runs",
            remedy_label="Open the run",
        )

    headline = f"Ready to deploy to {sentence(sorted(launchable))}."
    if any(outcome(run) == LIVE for run in runs[:RECENT]):
        headline = f"Running now, and safe to deploy to {sentence(sorted(launchable))}."

    # A missed objective is `degraded`, not `failed`: it ran, and the result is
    # not what the repository says it should be. Nothing is broken right now,
    # so the sentence still answers the question the page is opened with.
    if breaching:
        first = breaching[0]
        return Verdict(
            state=DEGRADED,
            headline=f"{headline[:-1]}, and an objective is being missed.",
            note=f"{first.title.capitalize()}: {first.detail}. Nothing has failed "
            "recently; the target has.",
            remedy="open-delivery",
            remedy_label="See the objective",
        )

    step = setup.next_step
    waiting = [one for one in catalog.environments if not one.usable]
    if waiting:
        first = waiting[0]
        rest = len(catalog.environments)
        return Verdict(
            state=READY,
            headline=headline,
            note=f"{first.name} has {first.reason or 'no host source'}, so nothing can "
            f"run there. Give it one and all {rest} environments are live.",
            remedy="open-environments",
            remedy_label="Give it an inventory",
        )
    if step is not None:
        return Verdict(
            state=READY,
            headline=headline,
            note=f"{step.title} and Ordane can also report {_lower(step.unlocks)}.",
            remedy=step.remedy,
            remedy_label=step.button,
        )
    if all(outcome(run) == OK for run in runs[:RECENT]) and runs:
        return Verdict(
            state=READY,
            headline=headline,
            note="Every environment is reachable, every measure has a source, and "
            "nothing has failed recently.",
        )
    return Verdict(
        state=READY,
        headline=headline,
        note="Nothing has run through this console yet. The first run fills the first "
        "gap in the measures below.",
        remedy="open-actions",
        remedy_label="Run something",
    )


def _failed_headline(failed: list) -> str:
    if len(failed) == 1:
        return f"{failed[0].name} failed. Look before deploying."
    return f"{len(failed)} of the last {RECENT} runs failed."


def _lower(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text
