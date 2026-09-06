"""Turns Ansible's own output into a result you can read at a glance.

Everything here is derived from the text a run already produced. Nothing is
inferred: a run whose output holds no recap reports that it has no recap.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_RECAP_HEADER = re.compile(r"^PLAY RECAP\b")
_RECAP_ROW = re.compile(
    r"^(?P<host>\S+)\s*:\s*"
    r"ok=(?P<ok>\d+)\s+"
    r"changed=(?P<changed>\d+)\s+"
    r"unreachable=(?P<unreachable>\d+)\s+"
    r"failed=(?P<failed>\d+)"
    r"(?:\s+skipped=(?P<skipped>\d+))?"
    r"(?:\s+rescued=(?P<rescued>\d+))?"
    r"(?:\s+ignored=(?P<ignored>\d+))?"
)

_TASK = re.compile(r"^(?:TASK|HANDLER)\s+\[(?P<name>.*?)\]\s*\**\s*$")
_PLAY = re.compile(r"^PLAY\s+\[(?P<name>.*?)\]\s*\**\s*$")
_OUTCOME = re.compile(r"^(?P<state>fatal|failed|unreachable):\s+\[(?P<host>[^\]]+)\]")
# `ansible` answers per host and prints no recap at all: `web1 | SUCCESS => {`.
# Without this a probe's whole answer was a wall of JSON with no result panel
# over it, which is the one thing a probe is asked for.
_ASKED = re.compile(
    r"^(?P<host>[^\s|]+)\s*\|\s*(?P<state>SUCCESS|CHANGED|FAILED|UNREACHABLE|SKIPPED)!?\b"
)

_MSG = re.compile(r'"msg":\s*"(?P<msg>(?:[^"\\]|\\.){0,400})"')

MAX_FAILURES = 25
MAX_MESSAGE = 300


@dataclass(frozen=True)
class HostResult:
    host: str
    ok: int = 0
    changed: int = 0
    unreachable: int = 0
    failed: int = 0
    skipped: int = 0
    rescued: int = 0
    ignored: int = 0

    @property
    def bad(self) -> bool:
        return bool(self.failed or self.unreachable)

    @property
    def state(self) -> str:
        if self.bad:
            return "failed"
        return "changed" if self.changed else "ok"


@dataclass(frozen=True)
class Failure:
    host: str
    task: str
    kind: str
    message: str = ""


@dataclass
class Summary:
    hosts: list[HostResult] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    tasks: int = 0
    plays: int = 0
    has_recap: bool = False
    truncated_failures: int = 0

    @property
    def changed(self) -> int:
        return sum(h.changed for h in self.hosts)

    @property
    def failed(self) -> int:
        return sum(h.failed + h.unreachable for h in self.hosts)

    @property
    def ok(self) -> int:
        return sum(h.ok for h in self.hosts)

    @property
    def unreachable_hosts(self) -> list[str]:
        return [h.host for h in self.hosts if h.unreachable]

    @property
    def headline(self) -> str:
        """One line a person can read without opening the log."""
        if not self.has_recap:
            return ""
        hosts = f"{len(self.hosts)} host" + ("s" if len(self.hosts) != 1 else "")
        parts = [hosts, f"{self.changed} changed"]
        if self.failed:
            parts.append(f"{self.failed} failed")
        return ", ".join(parts)

    def as_record(self) -> dict:
        return {
            "hosts": [asdict(h) for h in self.hosts],
            "failures": [asdict(f) for f in self.failures],
            "tasks": self.tasks,
            "plays": self.plays,
            "has_recap": self.has_recap,
            "truncated_failures": self.truncated_failures,
        }

    @classmethod
    def from_record(cls, record: dict) -> Summary:
        return cls(
            hosts=[HostResult(**h) for h in record.get("hosts", [])],
            failures=[Failure(**f) for f in record.get("failures", [])],
            tasks=int(record.get("tasks", 0)),
            plays=int(record.get("plays", 0)),
            has_recap=bool(record.get("has_recap", False)),
            truncated_failures=int(record.get("truncated_failures", 0)),
        )


def _message_from(line: str) -> str:
    match = _MSG.search(line)
    if not match:
        return ""
    return match.group("msg").encode().decode("unicode_escape", errors="replace")[:MAX_MESSAGE]


def from_asked(text: str) -> Summary:
    """The recap `ansible` never prints, built from what it answers instead.

    One line per host, `web1 | SUCCESS => {…}`, so a question asked of a host
    group reads the same way a playbook run does.
    """
    summary = Summary()
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = _ANSI.sub("", raw)
        found = _ASKED.match(line)
        if not found:
            continue
        host = found.group("host")
        if host in seen:
            continue
        seen.add(host)
        state = found.group("state").rstrip("!").upper()
        summary.hosts.append(
            HostResult(
                host=host,
                ok=1 if state in ("SUCCESS", "CHANGED") else 0,
                changed=1 if state == "CHANGED" else 0,
                unreachable=1 if state == "UNREACHABLE" else 0,
                failed=1 if state == "FAILED" else 0,
                skipped=1 if state == "SKIPPED" else 0,
            )
        )
        if state in ("FAILED", "UNREACHABLE"):
            summary.failures.append(
                Failure(
                    host=host,
                    task="the question asked",
                    kind=state.lower(),
                    message=_message_from(line),
                )
            )
    summary.has_recap = bool(summary.hosts)
    return summary


def parse(output: str) -> Summary:
    """Reads a run's captured output and reports what Ansible said happened."""
    summary = Summary()
    task = ""
    in_recap = False
    dropped = 0

    for raw in output.splitlines():
        line = _ANSI.sub("", raw).rstrip()

        if _RECAP_HEADER.match(line):
            in_recap = True
            summary.has_recap = True
            continue

        if in_recap:
            row = _RECAP_ROW.match(line)
            if row:
                summary.hosts.append(
                    HostResult(
                        host=row.group("host"),
                        **{
                            key: int(row.group(key) or 0)
                            for key in (
                                "ok",
                                "changed",
                                "unreachable",
                                "failed",
                                "skipped",
                                "rescued",
                                "ignored",
                            )
                        },
                    )
                )
                continue
            if line.strip():
                in_recap = False

        play = _PLAY.match(line)
        if play:
            summary.plays += 1
            continue

        found = _TASK.match(line)
        if found:
            summary.tasks += 1
            task = found.group("name")
            continue

        outcome = _OUTCOME.match(line)
        if outcome:
            if len(summary.failures) < MAX_FAILURES:
                summary.failures.append(
                    Failure(
                        host=outcome.group("host"),
                        task=task or "(before any task)",
                        kind=outcome.group("state"),
                        message=_message_from(line),
                    )
                )
            else:
                dropped += 1

    summary.truncated_failures = dropped
    return summary


@dataclass(frozen=True)
class Progress:
    """Where a run has got to, read from what it has printed so far."""

    play: str = ""
    task: str = ""
    plays: int = 0
    tasks: int = 0

    @property
    def known(self) -> bool:
        return bool(self.task or self.play)

    @property
    def summary(self) -> str:
        """`TASK [Deploy the release] · 12 tasks in`, or as much of it as is known."""
        if self.task:
            counted = f"{self.tasks} tasks in" if self.tasks > 1 else "first task"
            return f"{self.task} · {counted}"
        return self.play or ""


def progress(text: str) -> Progress:
    """The play and task a run is on, from the output it has printed so far.

    `parse` runs once, at the end, over a whole captured buffer: which is why
    nothing could say what a live run was doing. This reads the same two
    headers it already matches, cheaply enough to run on every chunk.
    """
    play = task = ""
    plays = tasks = 0
    for line in (text or "").splitlines():
        found = _PLAY.match(line)
        if found:
            play = found.group("name")
            plays += 1
            continue
        found = _TASK.match(line)
        if found:
            task = found.group("name")
            tasks += 1
    return Progress(play=play, task=task, plays=plays, tasks=tasks)
