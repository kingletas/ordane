"""What the configuration says about a target beyond how to run it.

A target says *what command*. A runbook says *who owns this, when it was last
looked at, what has to be true before it runs, what proves it worked, and what
to reach for when it does not*.

**All of it is declared and none of it is inferred.** A precheck nobody named
does not run, and a recovery nobody wrote is not offered: an undo that is
assumed is worse than one that is absent, because somebody plans around it.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from datetime import date

# How long a runbook stands before it is worth looking at again. Not a rule
# about how often anything changes: a rule about how long nobody has checked.
REVIEW_MONTHS = 12


@dataclass(frozen=True)
class Policy:
    """What has to be true before this target may be launched at all.

    Every one of these is a decision the control plane's own file makes. None
    of them is a default, because a threshold nobody chose is one nobody meant.
    """

    max_hosts: int = 0
    refs: tuple[str, ...] = ()
    clean_tree: bool = False

    @property
    def any(self) -> bool:
        return bool(self.max_hosts or self.refs or self.clean_tree)


@dataclass(frozen=True)
class Runbook:
    """The operational half of a target: who, when, what proves it, what undoes it."""

    target: str
    owner: str = ""
    reviewed: str = ""
    docs: str = ""
    validate: bool = False
    # The playbook this target runs, where a Makefile is what runs it. Named
    # rather than inferred: a recipe can call anything, and guessing which
    # playbook it meant would be a listing about the wrong file.
    playbook: str = ""
    precheck: str = ""
    postcheck: str = ""
    recovery: str = ""
    policy: Policy = field(default_factory=Policy)

    @property
    def documented(self) -> bool:
        return bool(self.owner and self.reviewed)

    def stale(self, today: date | None = None) -> bool:
        """Whether nobody has looked at this in a year. Unreviewed is not stale."""
        looked = _read_date(self.reviewed)
        if looked is None:
            return False
        now = today or date.today()
        months = (now.year - looked.year) * 12 + (now.month - looked.month)
        return months >= REVIEW_MONTHS

    def condition(self, today: date | None = None) -> str:
        """`owned`, `unowned`, `stale`: what a catalogue would sort on."""
        if self.stale(today):
            return "stale"
        return "owned" if self.documented else "unowned"


# The four things a runbook does, in the order it does them. `validate` runs
# the control plane's own declared checks in their container; the other three
# are targets.
VALIDATE = "validate"
PRECHECK = "precheck"
OPERATION = "operation"
POSTCHECK = "postcheck"


@dataclass(frozen=True)
class Step:
    """One target in a runbook's sequence, and what it is there to do."""

    kind: str
    target: str

    @property
    def sentence(self) -> str:
        return {
            VALIDATE: "Running this control plane's own checks",
            PRECHECK: f"Checking first: {self.target}",
            OPERATION: f"Running {self.target}",
            POSTCHECK: f"Checking it worked: {self.target}",
        }.get(self.kind, self.target)


def steps(book: Runbook) -> tuple[Step, ...]:
    """What a launch of this runbook actually runs, in order."""
    found = [Step(VALIDATE, "")] if book.validate else []
    if book.precheck:
        found.append(Step(PRECHECK, book.precheck))
    found.append(Step(OPERATION, book.target))
    if book.postcheck:
        found.append(Step(POSTCHECK, book.postcheck))
    return tuple(found)


def after(book: Runbook, done: str, ok: bool) -> Step | None:
    """What follows the step that just ended, or nothing.

    A failure stops the sequence, and a failed operation does not run its postcheck:
    asking a postcheck about a change that did not happen reports the same failure
    twice. The recovery action is offered instead, where one was declared.
    """
    if not ok:
        return None
    order = steps(book)
    for index, step in enumerate(order):
        if step.kind == done:
            return order[index + 1] if index + 1 < len(order) else None
    return None


@dataclass(frozen=True)
class Refusal:
    """Why a run may not go, in the words somebody would use to fix it."""

    reason: str
    detail: str = ""


def refusals(runbook: Runbook, *, hosts: int, ref: str, dirty: bool) -> list[Refusal]:
    """Every policy this launch would break. Empty means it may go.

    Counted rather than judged: the console reports what the file said, and the
    file is where somebody decided it.
    """
    found: list[Refusal] = []
    policy = runbook.policy
    if policy.max_hosts and hosts > policy.max_hosts:
        found.append(
            Refusal(
                f"This would reach {hosts} hosts and {runbook.target} allows {policy.max_hosts}.",
                "Narrow it with a host limit, or raise `policy.max_hosts` in the configuration.",
            )
        )
    if policy.refs and not _matches(ref, policy.refs):
        allowed = ", ".join(policy.refs)
        found.append(
            Refusal(
                f"{runbook.target} runs from {allowed}, and this checkout is on "
                f"{ref or 'no branch'}.",
                "Switch the ref, or widen `policy.refs`.",
            )
        )
    if policy.clean_tree and dirty:
        found.append(
            Refusal(
                f"{runbook.target} will not run from a working tree with uncommitted changes.",
                "A deploy from a dirty tree is one nobody can reproduce from a commit.",
            )
        )
    return found


@dataclass(frozen=True)
class Use:
    """One runbook that names another target, and what it uses it as."""

    target: str
    role: str

    @property
    def sentence(self) -> str:
        return f"{self.target}: {ROLE_WORDS.get(self.role, self.role)}"


ROLE_WORDS = {
    "precheck": "checks with this first",
    "postcheck": "proves itself with this",
    "recovery": "recovers with this",
}


def used_by(targets, name: str) -> list[Use]:
    """Which runbooks name this target as their check or their recovery.

    Worth knowing before changing one: a target that three runbooks lean on is
    not the same thing as a target nobody calls.
    """
    if not name:
        return []
    found: list[Use] = []
    for other, spec in (targets or {}).items():
        if other == name:
            continue
        book = read(other, spec)
        for role in ("precheck", "postcheck", "recovery"):
            if getattr(book, role) == name:
                found.append(Use(target=other, role=role))
    return sorted(found, key=lambda one: (one.target, one.role))


def read(target: str, spec) -> Runbook:
    """One target's runbook, from whatever the configuration declared."""
    if not isinstance(spec, dict):
        return Runbook(target=target)
    declared = spec.get("policy") if isinstance(spec.get("policy"), dict) else {}
    return Runbook(
        target=target,
        owner=str(spec.get("owner", "") or ""),
        reviewed=str(spec.get("reviewed", "") or ""),
        docs=str(spec.get("docs", "") or ""),
        validate=bool(spec.get("validate")),
        playbook=str(spec.get("playbook", "") or ""),
        precheck=str(spec.get("precheck", "") or ""),
        postcheck=str(spec.get("postcheck", "") or ""),
        recovery=str(spec.get("recovery", "") or ""),
        policy=Policy(
            max_hosts=_read_int(declared.get("max_hosts")),
            refs=_read_list(declared.get("refs")),
            clean_tree=bool(declared.get("clean_tree")),
        ),
    )


def _matches(ref: str, patterns: tuple[str, ...]) -> bool:
    """`release/*` is how a control plane names a family of branches."""
    return any(fnmatch.fnmatch(ref or "", one) for one in patterns)


def _read_list(value) -> tuple[str, ...]:
    """A list, or nothing. `refs: main` is a string, and a string iterates into
    four one-letter patterns that refuse every launch: a policy written wrongly
    must ask for nothing rather than for the impossible."""
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(one) for one in value if str(one))


def _read_int(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _read_date(text: str) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except (TypeError, ValueError):
        return None
