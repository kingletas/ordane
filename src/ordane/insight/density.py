"""How a history of fifty runs a day is read without becoming a log.

A repository that pings every half hour produces roughly fifty runs a day,
forty-eight of which say the same thing. Listed one per line that stops being
information. Three rules keep it readable, and all three are here rather than
in a view, so the desktop, the terminal and the browser fold the same way.

1. A row must earn its line. Routine passes that changed nothing fold into one
   summary row that still prints its count, so nothing is hidden, only folded.
2. Print only what deviates. Zero is not news, and an unremarkable duration is
   not either.
3. Shape before text. A day of runs is a ribbon of ticks before it is a list.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..presentation import language
from ..presentation.text import clock, day, moment, plural, since, took
from ..record.store import Run

# Where a run came from. Nothing here schedules anything yet, and `schedule`
# says so honestly: it exists because a fixture and a future cron both need a
# word for a run nobody pressed a button for.
BY_HAND = "hand"
BY_REPEAT = "repeat"
BY_STEP = "step"
BY_SCHEDULE = "schedule"

# What the ribbon covers, and what "recent" means on Overview.
RIBBON_HOURS = 24

# Overview shows at most this many rows that deviated, plus one rolled row.
# The full history is one click away and does not need a preview of itself.
OVERVIEW_ROWS = 5

# A duration is worth printing when it is this much of the median for the same
# action. Below it the number is noise with a unit attached.
UNUSUAL = 2.0
MIN_DURATION_SAMPLE = 4

# The four states, as the ramp names them.
OK = "ok"
WAIT = "wait"
WARN = "warn"
FAIL = "fail"
LIVE = "live"
MUTE = "mute"

# The states that mean a run happened and its result is not what the repository
# says. An environment in one of these is judged on it.
DEGRADED_STATES = (WARN, FAIL)

_WORDS = {
    OK: "Passed",
    WARN: "Needs a look",
    FAIL: "Failed",
    LIVE: "Running",
    MUTE: "Stopped",
}


def outcome(run: Run) -> str:
    """One of the four states, plus `live` for a run that has not ended.

    A run that finished with a non-zero exit failed. One that finished cleanly
    but left a host unreachable, or reported a failed task in its recap, ran
    and did not do what the repository says — which is degraded, not failure.
    """
    if run.state == "running":
        return LIVE
    if run.state in ("failed", "error"):
        return FAIL
    if run.state == "cancelled":
        return MUTE
    result = run.result
    if result.failed or result.unreachable_hosts:
        return WARN
    return OK


def outcome_word(run: Run) -> str:
    return _WORDS.get(outcome(run), language.state_name(run.state))


def changed(run: Run) -> int:
    return run.result.changed


def routine(run: Run) -> bool:
    """Whether this run is one of the forty-eight that say the same thing.

    It never covers a run that changed something, failed, is still going, or
    that somebody launched by hand. If you pressed the button you get your own
    line: you were there, and you will look for it.
    """
    if outcome(run) != OK:
        return False
    if changed(run):
        return False
    return (run.origin or BY_HAND) in (BY_REPEAT, BY_STEP, BY_SCHEDULE)


def worth_a_look(run: Run) -> bool:
    """The default filter. It never hides a failure, a change or a hand launch."""
    return not routine(run)


@dataclass(frozen=True)
class Row:
    """One run that earned its own line."""

    run: Run
    state: str
    word: str
    action: str
    environment: str
    note: str
    when: str

    kind: str = "run"


@dataclass(frozen=True)
class Rolled:
    """Consecutive routine passes, folded, with the count still on the page."""

    runs: list[Run]
    actions: list[str]
    environment: str
    when: str

    kind: str = "rolled"

    @property
    def count(self) -> int:
        return len(self.runs)

    @property
    def headline(self) -> str:
        return f"{self.count} passed"

    @property
    def what(self) -> str:
        return "Routine runs — " + ", ".join(self.actions)

    @property
    def note(self) -> str:
        return "nothing changed on any host"


@dataclass(frozen=True)
class More:
    """The tail of a day that is longer than the ceiling allows."""

    count: int
    kind: str = "more"


@dataclass(frozen=True)
class Tick:
    """One run on the ribbon: short and pale for routine, full height otherwise."""

    state: str
    tall: bool
    run_id: str = ""


@dataclass(frozen=True)
class Ribbon:
    """A day at a glance, answered before a single word is read."""

    ticks: list[Tick] = field(default_factory=list)
    since: str = ""
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.ticks)

    @property
    def sentence(self) -> str:
        """`44 passed, 2 changed something, 1 failed, 1 still going`."""
        parts = []
        for key, word in (
            (OK, "passed"),
            ("changed", "changed something"),
            (WARN, "did not match the repository"),
            (FAIL, "failed"),
            (MUTE, "were stopped"),
            (LIVE, "still going"),
        ):
            count = self.counts.get(key, 0)
            if count:
                parts.append(f"{count} {word}")
        return ", ".join(parts)


def ribbon(runs: list[Run], hours: int = RIBBON_HOURS) -> Ribbon:
    """The last day of runs as ticks, oldest first, and the counts under them."""
    window = recent(runs, hours)
    ticks: list[Tick] = []
    counts: dict[str, int] = {}
    for run in reversed(window):
        state = outcome(run)
        moved = bool(changed(run))
        tall = state in (FAIL, WARN, LIVE) or moved
        ticks.append(
            Tick(
                state="changed" if (moved and state == OK) else state,
                tall=tall,
                run_id=run.id,
            )
        )
        counts[state] = counts.get(state, 0) + 1
        if moved:
            counts["changed"] = counts.get("changed", 0) + 1
    oldest = window[-1] if window else None
    return Ribbon(ticks=ticks, since=moment(oldest.started) if oldest else "", counts=counts)


def recent(runs: list[Run], hours: int = RIBBON_HOURS) -> list[Run]:
    """The runs inside the window, newest first. `runs` is already newest first."""
    limit = hours * 3600
    kept = []
    for run in runs:
        elapsed = since(run.started)
        if elapsed is None or elapsed > limit:
            break
        kept.append(run)
    return kept


def fold(runs: list[Run], ceiling: int = 0, under_a_day: bool = False) -> list:
    """The rows a list actually draws: deviations in order, routine passes folded.

    Consecutive routine passes in the same environment collapse into one
    `Rolled`. `ceiling` caps how many `Row`s are drawn before a `More` stands
    for the rest; the rolled row is never what gets cut, because it is already
    a summary.
    """
    rows: list = []
    group: list[Run] = []

    def flush() -> None:
        if not group:
            return
        actions: list[str] = []
        for one in group:
            if one.name not in actions:
                actions.append(one.name)
        rows.append(
            Rolled(
                runs=list(group),
                actions=actions,
                environment=group[0].environment,
                when=clock(group[0].started) if under_a_day else moment(group[0].started),
            )
        )
        group.clear()

    medians = _medians(runs)
    for run in runs:
        if routine(run) and (not group or group[0].environment == run.environment):
            group.append(run)
            continue
        flush()
        if routine(run):
            group.append(run)
            continue
        rows.append(_row(run, medians, under_a_day))
    flush()

    if not ceiling:
        return rows
    drawn: list = []
    shown = 0
    for row in rows:
        if row.kind == "run":
            if shown >= ceiling:
                continue
            shown += 1
        drawn.append(row)
    cut = sum(1 for row in rows if row.kind == "run") - shown
    if cut:
        drawn.append(More(count=cut))
    return drawn


def by_day(runs: list[Run]) -> list[tuple[str, list[Run]]]:
    """The runs in order, split where the day changes."""
    grouped: list[tuple[str, list[Run]]] = []
    for run in runs:
        heading = day(run.started)
        if grouped and grouped[-1][0] == heading:
            grouped[-1][1].append(run)
        else:
            grouped.append((heading, [run]))
    return grouped


def _row(run: Run, medians: dict[str, float], under_a_day: bool) -> Row:
    return Row(
        run=run,
        state=outcome(run),
        word=outcome_word(run),
        action=run.name,
        environment=run.environment,
        note=note(run, medians.get(run.name)),
        when=clock(run.started) if under_a_day else moment(run.started),
    )


def note(run: Run, median: float | None = None) -> str:
    """The one fact that explains the outcome, as a fragment rather than a column.

    Zero is not news: an unchanged host count and an unremarkable duration are
    left out, not rendered as `0`.
    """
    result = run.result
    if run.state == "running":
        moved = [one for one in result.hosts if one.changed]
        if moved and result.hosts:
            return f"{len(moved)} of {plural(len(result.hosts), 'host')} changed so far"
        return "still going"
    if run.state in ("failed", "error"):
        first = result.failures[0] if result.failures else None
        if first is not None:
            what = first.message or first.kind
            return f"{first.host}: {_short(what)}"
        if run.exit_code is not None:
            return f"exit {run.exit_code}"
        return "it did not start"
    if run.state == "cancelled":
        return "stopped from here"
    unreachable = result.unreachable_hosts
    if unreachable:
        return f"{', '.join(unreachable[:2])} did not answer"
    if result.failed:
        return f"{plural(result.failed, 'task')} did not pass"
    moved = [one for one in result.hosts if one.changed]
    if moved:
        return f"{len(moved)} of {plural(len(result.hosts), 'host')} changed"
    if median and run.duration_s and run.duration_s > median * UNUSUAL:
        return f"took {took(run.duration_s)}, about {run.duration_s / median:.0f}× its usual"
    if result.hosts:
        return plural(len(result.hosts), "host")
    return ""


def _short(text: str, limit: int = 64) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _medians(runs: list[Run]) -> dict[str, float]:
    """How long each action usually takes, so `unusual` means something."""
    seen: dict[str, list[float]] = {}
    for run in runs:
        if run.duration_s and run.state == "succeeded":
            seen.setdefault(run.name, []).append(run.duration_s)
    return {
        name: statistics.median(values)
        for name, values in seen.items()
        if len(values) >= MIN_DURATION_SAMPLE
    }
