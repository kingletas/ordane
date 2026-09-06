"""What a run told the outside world, read back out of its own output.

A deploy here opens a PagerDuty maintenance window, marks the release in New
Relic, posts a Noibu webhook and says something in Slack: **and every one of
those is `failed_when: false`**, because instrumentation must never be the
reason a release is lost. The playbook then says out loud which of them landed,
in a task written for exactly that reason.

The console showed that as one line in a wall of output. This reads it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# The task's own name is declared in the configuration, so nothing here guesses
# which line matters. `ok: [host] => {` then a JSON object is what Ansible
# prints for a `debug` whose `msg` is a mapping: checked against a real run
# rather than remembered.
_TASK = re.compile(r"^TASK\s+\[(?P<name>.*?)\]\s*\**\s*$")
_ANSWER = re.compile(r"^(?:ok|changed):\s+\[[^\]]+\]\s*=>\s*\{\s*$")

LANDED = "landed"
MISSED = "missed"
UNCLEAR = "unclear"

# `0 of 3 apps FAILED` says nothing failed. A substring match for FAILED would
# call the healthiest possible answer a failure, which is the one reading this
# module must not get wrong.
_NONE_FAILED = re.compile(r"^\s*0\s+of\s+\d+\b", re.IGNORECASE)
_FAILED = re.compile(r"\bfail", re.IGNORECASE)


@dataclass(frozen=True)
class Notice:
    """One thing a run told, and whether it got through."""

    name: str
    detail: str

    @property
    def state(self) -> str:
        if _NONE_FAILED.match(self.detail):
            return LANDED
        if _FAILED.search(self.detail):
            return MISSED
        return LANDED if self.detail.strip().lower() == "ok" else UNCLEAR


@dataclass
class Told:
    notices: list[Notice] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(self.notices)

    @property
    def missed(self) -> list[Notice]:
        return [one for one in self.notices if one.state == MISSED]

    @property
    def summary(self) -> str:
        if not self.notices:
            return ""
        landed = sum(1 for one in self.notices if one.state == LANDED)
        return f"{landed} of {len(self.notices)} landed"


def read(output: str, task: str) -> Told:
    """The notifications a run reported, from the task the configuration names."""
    if not task:
        return Told()
    found: list[Notice] = []
    lines = (output or "").splitlines()
    for index, line in enumerate(lines):
        named = _TASK.match(_strip(line))
        if not named or named.group("name").strip() != task.strip():
            continue
        told = _object_after(lines, index + 1)
        for name, detail in told.items():
            found.append(Notice(name=str(name), detail=_flat(detail)))
        if found:
            break
    return Told(notices=found)


def _object_after(lines: list[str], start: int) -> dict:
    """The `msg` mapping of the first answer under a task, or nothing."""
    for index in range(start, min(start + 20, len(lines))):
        if _TASK.match(_strip(lines[index])):
            return {}
        if not _ANSWER.match(_strip(lines[index])):
            continue
        block = ["{"]
        depth = 1
        for line in lines[index + 1 :]:
            block.append(_strip(line))
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                break
        try:
            record = json.loads("\n".join(block))
        except ValueError:
            return {}
        message = record.get("msg")
        return message if isinstance(message, dict) else {}
    return {}


def _flat(value) -> str:
    """Ansible folds a long expression onto one line; so does this."""
    return " ".join(str(value).split())


def _strip(line: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).rstrip()
