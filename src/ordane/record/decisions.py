"""What somebody changed, as against what somebody ran.

The run store answers *what happened*. It has never answered *who decided
this*, and the console grew a button that can widen the list of environments it
will launch against: a branch carries its own configuration, so switching a
ref can allow production where the ref before it did not.

**A decision that changes what may be deployed and leaves no trace is the one
kind of history this tool exists to stop being missing.** Append-only, one line
per decision, in the same shape and the same directory as the runs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..core import identity

FILE_NAME = "decisions.jsonl"
SCHEMA = 1

# What kind of decision this was. Each one changes what the console will do
# next, which is what separates them from a preference.
REF = "ref"
ENVIRONMENTS = "environments"
OBJECTIVES = "objectives"
PLANE = "plane"

KINDS = (REF, ENVIRONMENTS, OBJECTIVES, PLANE)


@dataclass
class Decision:
    """One change, and enough of it to be read a year later."""

    at: str
    kind: str
    actor: str
    plane: str
    summary: str
    detail: dict = field(default_factory=dict)
    host: str = ""
    schema: int = SCHEMA

    @property
    def widened(self) -> list[str]:
        """Environments this decision allowed that were not allowed before."""
        return [str(one) for one in self.detail.get("widened") or []]

    def as_record(self) -> dict:
        return asdict(self)


class DecisionStore:
    """Append-only, and never a reason a decision cannot be taken."""

    def __init__(self, root: Path) -> None:
        self.path = Path(root) / FILE_NAME

    def record(self, *, kind: str, plane: str, summary: str, detail: dict | None = None) -> None:
        """Writes one. Swallows its own failure: instrumentation must not block a decision."""
        actor = identity.who()
        decision = Decision(
            at=_now(),
            kind=kind if kind in KINDS else PLANE,
            actor=actor.name,
            host=actor.host,
            plane=plane,
            summary=summary,
            detail=detail or {},
        )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(decision.as_record(), separators=(",", ":")) + "\n")
        except OSError:
            return

    def all(self, plane: str = "") -> list[Decision]:
        """Newest first, skipping any line that will not parse."""
        found: list[Decision] = []
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                decision = Decision(
                    **{k: v for k, v in record.items() if k in Decision.__annotations__}
                )
            except (ValueError, TypeError):
                continue
            if plane and decision.plane != plane:
                continue
            found.append(decision)
        return sorted(found, key=lambda one: one.at, reverse=True)


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
