"""Reads the DORA event log and release history; computes nothing it cannot source.

A measure with no data reports `no data` and says why. It never reports zero,
because a backfilled history would make zero look like a real measurement.
"""

from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..presentation.text import sentence, took

# A period-over-period comparison is only worth drawing when both halves hold
# enough releases to mean something. Six against seven is noise with an arrow
# on it, and an arrow is read as a finding.
TREND_DAYS = 180
MIN_TREND_SAMPLE = 8


@dataclass(frozen=True)
class Trend:
    """How this period compares with the one before it, when that is answerable.

    `rose` is what the number did and `better` is what that means, because the
    two come apart: a lead time that went up is an arrow pointing up and a
    result that is worse.
    """

    text: str
    rose: bool | None = None
    better: bool | None = None


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    value: str = ""
    detail: str = ""
    blocked: str = ""
    trend: Trend | None = None

    @property
    def has_data(self) -> bool:
        return bool(self.value) and not self.blocked

    @property
    def status(self) -> str:
        return "ok" if self.has_data else "nodata"


@dataclass(frozen=True)
class Slo:
    label: str
    target: str
    window: str
    value: str = ""
    blocked: str = ""
    attained: float | None = None

    @property
    def has_data(self) -> bool:
        return self.attained is not None and not self.blocked

    @property
    def status(self) -> str:
        if not self.has_data:
            return "nodata"
        return "ok" if self.attained is not None and self.attained >= self._target_pct else "breach"

    @property
    def _target_pct(self) -> float:
        try:
            return float(self.target.rstrip("%"))
        except ValueError:
            return 100.0


@dataclass(frozen=True)
class Release:
    date: str
    environment: str
    release: str
    outcome: str
    lead_time_days: float | None
    source: str


@dataclass(frozen=True)
class Series:
    """A short run of counts per period, for drawing rather than reading."""

    labels: list[str] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    caption: str = ""

    def __bool__(self) -> bool:
        return len(self.values) > 1


@dataclass(frozen=True)
class Snapshot:
    measures: list[Measure] = field(default_factory=list)
    slos: list[Slo] = field(default_factory=list)
    releases: list[Release] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cadence: Series = field(default_factory=Series)

    def measure(self, key: str) -> Measure | None:
        return next((m for m in self.measures if m.key == key), None)


def read_history(path: Path) -> list[Release]:
    """Parses the rolled-up release CSV the reporter commits."""
    if not path.is_file():
        return []
    releases: list[Release] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            lead = row.get("lead_time_days") or ""
            try:
                lead_value = float(lead) if lead else None
            except ValueError:
                lead_value = None
            releases.append(
                Release(
                    date=row.get("date", ""),
                    environment=row.get("env_name", ""),
                    release=row.get("release", ""),
                    outcome=row.get("outcome", ""),
                    lead_time_days=lead_value,
                    source=row.get("source", ""),
                )
            )
    return releases


def read_events(path: Path) -> list[dict]:
    """Parses the DORA deployment event log, skipping any malformed line."""
    if not path.is_file():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            events.append(record)
    return events


def _months_between(dates: list[str]) -> float:
    parsed = sorted(d for d in (_date(x) for x in dates) if d is not None)
    if len(parsed) < 2:
        return 0.0
    return max((parsed[-1] - parsed[0]).days / 30.44, 1.0)


def _date(text: str):
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except (ValueError, TypeError):
            continue
    return None


# `metrics.environments` in the config decides which environments count as a
# release. Without it, the historical default stands: production and nothing else.
DEFAULT_SCOPE = ("production",)


def _scope(scope: list[str] | None) -> list[str]:
    return [str(name) for name in (scope or DEFAULT_SCOPE)]


def _in_scope(releases: list[Release], scope: list[str]) -> list[Release]:
    return [r for r in releases if r.environment in scope and r.date]


def _scope_words(scope: list[str]) -> str:
    """`production`, or `staging and docker`: whatever the config named."""
    return sentence(scope) or "in-scope"


def _split_by_period(releases: list[Release], scope: list[str]) -> tuple[list, list]:
    """This period's releases and the one before it, most recent first."""
    now = datetime.now(UTC)
    edge = now - timedelta(days=TREND_DAYS)
    far = now - timedelta(days=TREND_DAYS * 2)
    recent, previous = [], []
    for release in _in_scope(releases, scope):
        when = _date(release.date)
        if when is None:
            continue
        if when >= edge:
            recent.append(release)
        elif when >= far:
            previous.append(release)
    return recent, previous


def _months() -> str:
    return f"{TREND_DAYS // 30} months"


def _cadence_trend(releases: list[Release], scope: list[str]) -> Trend | None:
    recent, previous = _split_by_period(releases, scope)
    if len(recent) < MIN_TREND_SAMPLE or len(previous) < MIN_TREND_SAMPLE:
        return None
    change = 100 * (len(recent) - len(previous)) / len(previous)
    if abs(change) < 5:
        return Trend(f"about the same as the previous {_months()}")
    word = "more often" if change > 0 else "less often"
    return Trend(
        f"{abs(change):.0f}% {word} than the previous {_months()}",
        rose=change > 0,
        better=change > 0,
    )


def _lead_time_trend(releases: list[Release], scope: list[str]) -> Trend | None:
    recent, previous = _split_by_period(releases, scope)
    now = [r.lead_time_days for r in recent if r.lead_time_days is not None]
    before = [r.lead_time_days for r in previous if r.lead_time_days is not None]
    if len(now) < MIN_TREND_SAMPLE or len(before) < MIN_TREND_SAMPLE:
        return None
    change = statistics.median(now) - statistics.median(before)
    if abs(change) < 0.5:
        return Trend(f"about the same as the previous {_months()}")
    word = "slower" if change > 0 else "faster"
    return Trend(
        f"{abs(change):.1f} days {word} than the previous {_months()}",
        rose=change > 0,
        better=change < 0,
    )


def _cadence(releases: list[Release], scope: list[str]) -> Measure:
    counted = _in_scope(releases, scope)
    where = _scope_words(scope)
    if len(counted) < 2:
        return Measure(
            "cadence",
            "Release cadence",
            blocked=f"fewer than two {where} releases on record",
        )
    span = _months_between([r.date for r in counted])
    rate = len(counted) / span if span else 0.0
    dates = sorted(r.date for r in counted if r.date)
    return Measure(
        "cadence",
        "Release cadence",
        value=f"{rate:.1f} / month",
        detail=f"{len(counted)} {where} releases, {dates[0]} to {dates[-1]}",
        trend=_cadence_trend(releases, scope),
    )


def _lead_time(releases: list[Release], scope: list[str]) -> Measure:
    recent_cutoff = datetime.now(UTC) - timedelta(days=365)
    values = [
        r.lead_time_days
        for r in _in_scope(releases, scope)
        if r.lead_time_days is not None
        and (_date(r.date) or datetime.min.replace(tzinfo=UTC)) >= recent_cutoff
    ]
    if not values:
        # The fallback widens the window, never the scope: a lead time computed
        # over environments the config excluded is a different number wearing
        # the same label.
        values = [
            r.lead_time_days for r in _in_scope(releases, scope) if r.lead_time_days is not None
        ]
        if not values:
            return Measure(
                "lead_time",
                "Time to production",
                blocked=f"no lead-time data for {_scope_words(scope)}",
            )
        return Measure(
            "lead_time",
            "Time to production",
            value=f"{statistics.median(values):.1f} d",
            detail=f"median of {len(values)} {_scope_words(scope)} releases, all time",
        )
    return Measure(
        "lead_time",
        "Time to production",
        value=f"{statistics.median(values):.1f} d",
        detail=f"median of {len(values)} releases in the last 12 months",
        trend=_lead_time_trend(releases, scope),
    )


def _failure_rate(events: list[dict], runs: list, scope: list[str]) -> Measure:
    """Change failure rate needs incident data this tool does not read."""
    started = sum(1 for e in events if str(e.get("event", "")).endswith(".started"))
    if not started and not runs:
        return Measure(
            "failure_rate",
            "Release risk",
            blocked="no instrumented release yet: needs a cutover with a recorded start",
        )
    deploys = [
        r
        for r in runs
        if r.labels.get("deploy") == "true"
        and r.state != "running"
        and (not scope or r.environment in scope)
    ]
    if not deploys:
        where = f" for {', '.join(scope)}" if scope else ""
        return Measure(
            "failure_rate",
            "Release risk",
            blocked=f"no recorded deploy runs{where} yet",
        )
    failed = sum(1 for r in deploys if r.exit_code not in (0, None))
    return Measure(
        "failure_rate",
        "Release risk",
        value=f"{100 * failed / len(deploys):.0f}%",
        detail=f"{failed} of {len(deploys)} recorded deploy runs failed (console runs only)",
    )


def _recovery(runs: list, scope: list[str]) -> Measure:
    """How long a broken deploy stayed broken, measured from this console's own runs.

    It is the deployment that is restored here, not the service: nothing in
    this console reads an incident tracker, so a failure nobody deployed
    through is one it cannot see.
    """
    deploys = [
        r
        for r in runs
        if r.labels.get("deploy") == "true"
        and r.state in ("succeeded", "failed")
        and (not scope or r.environment in scope)
    ]
    if not deploys:
        where = f" for {', '.join(scope)}" if scope else ""
        return Measure("recovery", "Recovery time", blocked=f"no recorded deploy runs{where} yet")

    gaps = _recoveries(sorted(deploys, key=lambda r: r.started))
    if not gaps:
        return Measure(
            "recovery",
            "Recovery time",
            blocked="no failed deploy has been followed by one that succeeded",
        )
    return Measure(
        "recovery",
        "Recovery time",
        value=took(statistics.median(gaps)),
        detail=f"median of {len(gaps)} recoveries, from a failed deploy to the next that worked",
    )


def _recoveries(deploys: list) -> list[float]:
    """Seconds from each failure to the next success on the same environment."""
    broken: dict[str, datetime] = {}
    gaps: list[float] = []
    for run in deploys:
        when = _stamp(run.started)
        if when is None:
            continue
        if run.exit_code in (0, None):
            since = broken.pop(run.environment, None)
            if since is not None:
                gaps.append((when - since).total_seconds())
        else:
            # The first failure is when it broke; a second one before any fix
            # does not restart the clock.
            broken.setdefault(run.environment, when)
    return gaps


def _stamp(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _cutover_slos(runs: list, slo_specs: list[dict]) -> list[Slo]:
    finished = [
        r for r in runs if r.labels.get("cutover") == "true" and r.state in ("succeeded", "failed")
    ]
    slos: list[Slo] = []
    for spec in slo_specs:
        label = str(spec.get("label", "unnamed"))
        target = str(spec.get("target", ""))
        window = str(spec.get("window", ""))
        kind = str(spec.get("kind", ""))

        # An objective that names its environments counts only those. A run
        # against a throwaway fleet must never contribute to a service number.
        scope = [str(e) for e in spec.get("environments", []) or []]
        cutovers = [r for r in finished if not scope or r.environment in scope]
        if scope and not cutovers:
            slos.append(
                Slo(
                    label,
                    target,
                    window,
                    blocked=f"no cutover recorded for {', '.join(scope)}",
                )
            )
            continue

        if kind == "cutover_success":
            if not cutovers:
                slos.append(
                    Slo(label, target, window, blocked="no cutover has run through this console")
                )
                continue
            ok = sum(1 for r in cutovers if r.exit_code == 0)
            attained = 100 * ok / len(cutovers)
            slos.append(Slo(label, target, window, value=f"{attained:.0f}%", attained=attained))
        elif kind == "cutover_duration":
            limit = float(spec.get("limit_seconds", 2700))
            done = [r for r in cutovers if r.duration_s]
            if not done:
                slos.append(
                    Slo(label, target, window, blocked="no cutover has run through this console")
                )
                continue
            within = sum(1 for r in done if r.duration_s <= limit)
            attained = 100 * within / len(done)
            slos.append(Slo(label, target, window, value=f"{attained:.0f}%", attained=attained))
        else:
            slos.append(
                Slo(label, target, window, blocked=str(spec.get("blocked", "not instrumented")))
            )
    return slos


def cadence_series(releases: list[Release], scope: list[str], months: int = 18) -> Series:
    """Releases per calendar month, in the configured scope, most recent last."""
    dated = [(_date(r.date), r) for r in _in_scope(releases, scope)]
    stamped = [(d, r) for d, r in dated if d is not None]
    if len(stamped) < 2:
        return Series()

    counts: dict[str, int] = {}
    for when, _ in stamped:
        counts[when.strftime("%Y-%m")] = counts.get(when.strftime("%Y-%m"), 0) + 1

    latest = max(when for when, _ in stamped)
    keys: list[str] = []
    year, month = latest.year, latest.month
    for _ in range(months):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    keys.reverse()

    return Series(
        labels=keys,
        values=[float(counts.get(k, 0)) for k in keys],
        caption=f"releases a month, {keys[0]} to {keys[-1]}",
    )


def snapshot(
    *,
    history_path: Path,
    events_path: Path,
    runs: list,
    slo_specs: list[dict],
    scope: list[str] | None = None,
) -> Snapshot:
    """Everything the dashboard shows, with each gap named rather than zeroed."""
    releases = read_history(history_path)
    events = read_events(events_path)
    counted = _scope(scope)
    notes: list[str] = []

    if not releases:
        notes.append(f"No release history at {history_path}: run `make dora` in the repository.")
    if not events:
        notes.append(f"No DORA event log at {events_path}.")
    else:
        envs = sorted({str(e.get("env_name", "")) for e in events})
        if envs and not set(envs) & set(counted):
            notes.append(
                f"The event log holds {len(events)} events, all from: {', '.join(envs)}. "
                f"No {_scope_words(counted)} cutover has been instrumented yet."
            )

    measures = [
        _cadence(releases, counted),
        _lead_time(releases, counted),
        _failure_rate(events, runs, counted),
        _recovery(runs, counted),
    ]
    return Snapshot(
        measures=measures,
        slos=_cutover_slos(runs, slo_specs),
        releases=releases,
        events=events,
        notes=notes,
        cadence=cadence_series(releases, counted),
    )
