"""Reads a deploy ledger: the hash-chained audit log a playbook appends to.

Each line is a JSON record carrying the SHA-256 of the record before it, so an
edited, removed or reordered line breaks every link after it. The chain is
checked here with the same rules the writer uses rather than by trusting its
own verify command, and the records are then grouped into deployments so a
reader can see who did what, when, and whether anything is missing.

Nothing here writes to a ledger.
"""

from __future__ import annotations

import glob
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from ..presentation import language, text
from ..presentation.text import moment, took

GENESIS = "0" * 64

INTACT = "intact"
BROKEN = "broken"
EMPTY = "empty"
MISSING = "missing"
UNREADABLE = "unreadable"

SUCCEEDED = "succeeded"
BUILT_ONLY = "built-only"
# The deploy finished and its record does not say how, or says it did not work.
FINISHED = "finished"
FAILED = "failed"
STOPPED = "stopped"
UNFINISHED = "unfinished"
# Records in the ledger that no deploy.started opened: a warm-up run on its
# own, or a verify of a release deployed before this log began.
RECORDS_ONLY = "records"

# Where a playbook's inventories declare `audit.path`, read as the files are.
INVENTORY_VARS = (
    "inventory/*/group_vars/all.yml",
    "inventory/*/group_vars/all/*.yml",
    "inventories/*/group_vars/all.yml",
    "inventories/*/group_vars/all/*.yml",
)

FLAG = "flag"
CONFIG = "config"
INVENTORY = "inventory"


@dataclass(frozen=True)
class Actor:
    """Who ran a step, as the playbook resolved it on the control node."""

    git_email: str = ""
    os_user: str = ""
    control_host: str = ""
    remote_user: str = ""

    @classmethod
    def read(cls, raw: object) -> Actor:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            git_email=str(raw.get("git_email") or ""),
            os_user=str(raw.get("os_user") or ""),
            control_host=str(raw.get("control_host") or ""),
            remote_user=str(raw.get("remote_user") or ""),
        )

    @property
    def known(self) -> bool:
        return bool(self.git_email or self.os_user)

    @property
    def name(self) -> str:
        """The git identity where there is one, else the account."""
        return self.git_email or self.os_user or "someone unrecorded"

    @property
    def context(self) -> str:
        """`as alex on ops-laptop, connecting as deploy`."""
        parts = []
        if self.os_user and self.os_user != self.git_email:
            parts.append(f"as {self.os_user}")
        if self.control_host:
            parts.append(f"on {self.control_host}")
        said = " ".join(parts)
        if self.remote_user:
            said = (
                f"{said}, connecting as {self.remote_user}"
                if said
                else f"connecting as {self.remote_user}"
            )
        return said


@dataclass(frozen=True)
class Entry:
    """One record, trusted only when it sits inside an intact stretch of the chain."""

    seq: int
    event: str
    at: str
    environment: str
    release: str
    actor: Actor
    fields: dict
    hash: str = ""
    trusted: bool = True

    def get(self, key: str, default: object = "") -> object:
        return self.fields.get(key, default)

    def flag(self, key: str) -> bool | None:
        """A boolean the playbook may have written as `true`, `True` or `"false"`."""
        value = self.fields.get(key)
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "yes", "1")


@dataclass(frozen=True)
class Chain:
    """One ledger file: its records and whether the chain holding them is whole."""

    path: Path
    environment: str
    state: str
    entries: list[Entry] = field(default_factory=list)
    broken_line: int = 0
    reason: str = ""
    head: str = ""

    @property
    def intact(self) -> bool:
        return self.state == INTACT

    @property
    def untrusted(self) -> int:
        return sum(1 for e in self.entries if not e.trusted)


@dataclass(frozen=True)
class Approval:
    signer: str
    signing_key: str
    tag: str
    commit: str


@dataclass(frozen=True)
class Deployment:
    """One deploy attempt, from `deploy.started` to whatever was recorded after it."""

    environment: str
    release: str
    entries: list[Entry]

    def first(self, event: str) -> Entry | None:
        return next((e for e in self.entries if e.event == event), None)

    def last(self, event: str) -> Entry | None:
        return next((e for e in reversed(self.entries) if e.event == event), None)

    @property
    def trusted(self) -> bool:
        return all(e.trusted for e in self.entries)

    @property
    def start(self) -> Entry:
        return self.first("deploy.started") or self.entries[0]

    @property
    def started_at(self) -> str:
        return self.start.at

    @property
    def finished(self) -> Entry | None:
        return self.last("deploy.finished")

    @property
    def deployer(self) -> Actor:
        return self.start.actor

    @property
    def approval(self) -> Approval | None:
        entry = self.first("approval.verified")
        if entry is None:
            return None
        return Approval(
            signer=str(entry.get("signer")),
            signing_key=str(entry.get("signing_key")),
            tag=str(entry.get("tag")),
            commit=str(entry.get("commit")),
        )

    @property
    def verified(self) -> Entry | None:
        return self.last("deploy.verified")

    @property
    def build(self) -> Entry | None:
        return self.first("build.succeeded")

    @property
    def commit(self) -> str:
        build = self.build
        if build and build.get("commit"):
            return str(build.get("commit"))
        approval = self.approval
        return approval.commit if approval else ""

    @property
    def artefact(self) -> str:
        build = self.build
        return str(build.get("artefact_sha256")) if build else ""

    @property
    def cutover_artefact(self) -> str:
        cutover = self.first("cutover.started")
        return str(cutover.get("artefact_sha256")) if cutover else ""

    @property
    def artefact_matches(self) -> bool | None:
        """Whether the archive cut over is the one built; None when either is unrecorded."""
        if not self.artefact or not self.cutover_artefact:
            return None
        return self.artefact == self.cutover_artefact

    @property
    def approved_commit_matches(self) -> bool | None:
        """Whether the approved commit is the one that was built; None when either is unrecorded."""
        approval = self.approval
        build = self.build
        if approval is None or build is None or not approval.commit or not build.get("commit"):
            return None
        return approval.commit == build.get("commit")

    @property
    def backup_failed(self) -> Entry | None:
        return self.last("backup.failed")

    @property
    def backup(self) -> Entry | None:
        return self.last("backup.succeeded")

    @property
    def maintenance_window(self) -> bool | None:
        """Whether the maintenance page went up; None when the deploy never reached that point."""
        if self.first("maintenance.enabled"):
            return True
        succeeded = self.last("cutover.succeeded")
        if succeeded is not None and succeeded.flag("maintenance_window") is not None:
            return succeeded.flag("maintenance_window")
        started = self.first("cutover.started")
        if started is not None and started.flag("maintenance_window") is False:
            return False
        return None

    @property
    def maintenance_planned(self) -> bool:
        started = self.first("cutover.started")
        return started is not None and started.flag("maintenance_window") is True

    @property
    def warmup(self) -> Entry | None:
        return self.last("warmup.completed")

    @property
    def goes_live(self) -> bool:
        return self.start.flag("goes_live") is not False

    @property
    def others(self) -> list[tuple[Entry, Actor]]:
        """Steps recorded by someone other than the deployer, such as a later verify."""
        deployer = self.deployer
        return [(e, e.actor) for e in self.entries if e.actor.known and e.actor != deployer]

    @property
    def outcome(self) -> str:
        if self.first("deploy.started") is None:
            return RECORDS_ONLY
        finished = self.finished
        if finished is not None:
            said = str(finished.get("outcome") or "")
            if said == "success":
                return SUCCEEDED if self.goes_live else BUILT_ONLY
            # A finish is a finish. What it says about itself is a separate
            # question from whether it happened, and reading a finish with no
            # outcome as *no finish* calls a deploy unfinished while its last
            # record sits there saying otherwise.
            return FINISHED if not said else FAILED
        if self.backup_failed is not None:
            return STOPPED
        return UNFINISHED

    @property
    def last_step(self) -> Entry:
        """The last step of the deploy itself, leaving out a verify recorded afterwards."""
        steps = [e for e in self.entries if e.event != "deploy.verified"]
        return steps[-1] if steps else self.entries[-1]

    def span(self, key: str) -> float | None:
        """Seconds between the two records a span is measured over, or None if either is missing."""
        pair = SPAN_RECORDS.get(key)
        if pair is None:
            return None
        opening, closing = pair
        first, last = self.first(opening), self.last(closing)
        if first is None or last is None:
            return None
        start, end = _stamp(first.at), _stamp(last.at)
        if start is None or end is None or end < start:
            return None
        return (end - start).total_seconds()

    @property
    def spans(self) -> dict[str, float]:
        """Every span this deploy's records can carry, in the order a reader asks for them."""
        found = {key: self.span(key) for key in SPAN_RECORDS}
        return {key: value for key, value in found.items() if value is not None}

    @property
    def duration_s(self) -> float | None:
        finished = self.finished
        if finished is None:
            return None
        start, end = _stamp(self.started_at), _stamp(finished.at)
        if start is None or end is None:
            return None
        return max(0.0, (end - start).total_seconds())


# Each span is the gap between two records the ledger already carries. A phase
# with a record at only one end cannot be timed, and none is invented here.
SPAN_RECORDS = {
    "maintenance": ("maintenance.enabled", "cutover.succeeded"),
    "cutover": ("cutover.started", "cutover.succeeded"),
    "build": ("deploy.started", "build.succeeded"),
    "total": ("deploy.started", "deploy.finished"),
    "warmup": ("cutover.succeeded", "warmup.completed"),
    "to_verify": ("deploy.finished", "deploy.verified"),
}

# The one customers experience, so it leads wherever a timing is shown.
HEADLINE = "maintenance"


def record_hash(record: dict) -> str:
    """SHA-256 of the record's canonical JSON, leaving out its own hash."""
    body = {k: v for k, v in record.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read(path: Path, environment: str = "") -> Chain:
    """The chain in one file. Never raises: an unreadable ledger is a state, not a crash."""
    name = environment or _environment_from_name(path)
    if not path.exists():
        return Chain(path=path, environment=name, state=MISSING)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return Chain(path=path, environment=name, state=UNREADABLE, reason=str(exc))
    if not lines:
        return Chain(path=path, environment=name, state=EMPTY)

    entries: list[Entry] = []
    previous = GENESIS
    broken_line, reason = 0, ""
    for number, line in enumerate(lines, 1):
        record, problem = _parse(line)
        if not broken_line and problem:
            broken_line, reason = number, problem
        elif not broken_line:
            if record.get("seq") != number:
                broken_line, reason = number, f"seq is {record.get('seq')!r}, expected {number}"
            elif record.get("prev_hash") != previous:
                broken_line, reason = number, "prev_hash does not match the record before it"
            elif record.get("hash") != record_hash(record):
                broken_line, reason = number, "hash does not match the record's contents"
            else:
                previous = record["hash"]
        if record:
            entries.append(_entry(record, number, trusted=not broken_line))

    if not name and entries:
        name = entries[0].environment
    if broken_line:
        return Chain(
            path=path,
            environment=name,
            state=BROKEN,
            entries=entries,
            broken_line=broken_line,
            reason=reason,
            head=previous if previous != GENESIS else "",
        )
    return Chain(path=path, environment=name, state=INTACT, entries=entries, head=previous)


def deployments(chain: Chain) -> list[Deployment]:
    """Every deploy attempt in the chain, newest first.

    A `deploy.started` opens an attempt and the records after it join it. A
    verify is its own playbook run, so it joins the latest attempt of the same
    release wherever that sits.
    """
    attempts: list[list[Entry]] = []
    for entry in chain.entries:
        if entry.event == "deploy.verified":
            owner = next((a for a in reversed(attempts) if a[0].release == entry.release), None)
            if owner is not None:
                owner.append(entry)
                continue
            attempts.append([entry])
            continue
        current = attempts[-1] if attempts else None
        # Records with no deploy.started before them are not a deploy, and one
        # group of them beats a row each: the playbook's own warm-up suite
        # leaves four, and four rows read as four deploys that never finished.
        joins = (
            current is not None
            and entry.event != "deploy.started"
            and (not entry.release or entry.release == current[0].release)
        )
        if joins:
            current.append(entry)
        else:
            attempts.append([entry])
    found = [
        Deployment(
            environment=a[0].environment or chain.environment, release=a[0].release, entries=a
        )
        for a in attempts
    ]
    return list(reversed(found))


@dataclass(frozen=True)
class Source:
    """Where a ledger was found, and why this console looked there."""

    path: Path
    environment: str
    origin: str
    note: str = ""


def locate(repo: Path, declared: list[str], given: list[Path] | None = None) -> list[Source]:
    """The ledgers for this control plane: given on the command line, declared, or discovered.

    The first of the three that names anything wins, so a declaration is never
    quietly merged with a guess.
    """
    if given:
        return [Source(p.expanduser(), _environment_from_name(p), FLAG) for p in given]
    if declared:
        found: list[Source] = []
        for pattern in declared:
            expanded = str(Path(pattern).expanduser())
            base = expanded if Path(expanded).is_absolute() else str(repo / expanded)
            matches = sorted(glob.glob(base)) or ([base] if not glob.has_magic(base) else [])
            found += [Source(Path(m), _environment_from_name(Path(m)), CONFIG) for m in matches]
        return _unique(found)
    return _unique(_from_inventory(repo))


def _from_inventory(repo: Path) -> list[Source]:
    found: list[Source] = []
    for pattern in INVENTORY_VARS:
        for name in sorted(glob.glob(str(repo / pattern))):
            path = Path(name)
            environment = path.relative_to(repo).parts[1]
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            audit = raw.get("audit") if isinstance(raw, dict) else None
            where = audit.get("path") if isinstance(audit, dict) else None
            if not isinstance(where, str) or not where.strip():
                continue
            resolved = where.strip().replace("{{ playbook_dir }}", str(repo))
            if "{{" in resolved:
                found.append(
                    Source(
                        Path(resolved),
                        environment,
                        INVENTORY,
                        note="the path is a template this console does not evaluate",
                    )
                )
                continue
            found.append(Source(Path(resolved).expanduser(), environment, INVENTORY))
    return found


def _unique(sources: list[Source]) -> list[Source]:
    seen: set[Path] = set()
    kept = []
    for source in sources:
        if source.path in seen:
            continue
        seen.add(source.path)
        kept.append(source)
    return kept


def _environment_from_name(path: Path) -> str:
    """`staging.audit.jsonl` is staging's ledger."""
    name = path.name
    return name[: -len(".audit.jsonl")] if name.endswith(".audit.jsonl") else ""


def _stamp(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _parse(line: str) -> tuple[dict, str]:
    if not line.strip():
        return {}, "blank line"
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        return {}, f"not JSON ({exc.msg})"
    if not isinstance(record, dict):
        return {}, "not a JSON object"
    return record, ""


def _entry(record: dict, number: int, trusted: bool) -> Entry:
    seq = record.get("seq")
    return Entry(
        seq=seq if isinstance(seq, int) else number,
        event=str(record.get("event") or ""),
        at=str(record.get("recorded_at") or ""),
        environment=str(record.get("env_name") or ""),
        release=str(record.get("release") or ""),
        actor=Actor.read(record.get("actor")),
        fields=record,
        hash=str(record.get("hash") or ""),
        trusted=trusted,
    )


@dataclass(frozen=True)
class Answer:
    """One question a reviewer asks about a deploy, answered only from its records."""

    question: str
    answer: str
    detail: str = ""
    level: str = language.OK
    # Values somebody may want to paste: a commit, a checksum, a key.
    exact: tuple[str, ...] = ()


@dataclass(frozen=True)
class Step:
    """One line of a deploy's flow, and who stands behind it."""

    event: str
    name: str
    meaning: str
    at: str
    who: str
    role: str
    detail: str
    trusted: bool
    level: str = language.OK
    hash: str = ""
    # True when the person on this step is not the one who started the deploy.
    someone_else: bool = False

    @property
    def worth_naming(self) -> bool:
        """A name repeated on every step hides the one step somebody else took."""
        return self.someone_else or self.role != RUN_BY


def answers(deployment: Deployment, chain: Chain) -> list[Answer]:
    """Who, what, where, when, and whether it can be believed, in the order a reviewer asks."""
    return [
        _who_deployed(deployment),
        _who_approved(deployment),
        _what_went_out(deployment),
        _same_thing(deployment),
        _when_it_ran(deployment),
        _downtime(deployment),
        _backup(deployment),
        _did_it_work(deployment),
        _checked_since(deployment),
        _trust(deployment, chain),
    ]


RUN_BY = "run by"

STEP_ROLES = {
    "deploy.started": "requested by",
    "approval.verified": "approved by",
    "build.succeeded": "built on",
    "deploy.verified": "verified by",
}


def steps(deployment: Deployment) -> list[Step]:
    """The deploy's flow, one step per record, each naming who or what did it."""
    deployer = deployment.deployer.name
    found = []
    for entry in deployment.entries:
        who, role = entry.actor.name, RUN_BY
        if entry.event == "approval.verified":
            who = str(entry.get("signer") or "an unrecorded signer")
        elif entry.event == "build.succeeded" and entry.get("builder"):
            who = str(entry.get("builder"))
        role = STEP_ROLES.get(entry.event, RUN_BY)
        level = language.PROBLEM if entry.event == "backup.failed" else language.OK
        found.append(
            Step(
                event=entry.event,
                name=language.ledger_step(entry.event),
                meaning=language.ledger_step_meaning(entry.event),
                at=entry.at,
                who=who,
                role=role,
                detail=_step_detail(entry),
                trusted=entry.trusted,
                level=level if entry.trusted else language.PROBLEM,
                hash=entry.hash,
                someone_else=entry.event != "build.succeeded" and who != deployer,
            )
        )
    return found


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


def _short(value: str, size: int = 12) -> str:
    return value[:size] if value else ""


def _step_detail(entry: Entry) -> str:
    event = entry.event
    if event == "deploy.started":
        parts = [f"branch {entry.get('branch')}" if entry.get("branch") else ""]
        if entry.flag("reused_release"):
            parts.append("reusing a release already built")
        if entry.flag("goes_live") is False:
            parts.append("not going live")
        return "; ".join(p for p in parts if p)
    if event == "approval.verified":
        return f"signed tag {entry.get('tag')}"
    if event == "build.succeeded":
        return f"commit {_short(str(entry.get('commit')))}"
    if event == "cutover.started":
        window = entry.flag("maintenance_window")
        return (
            "with a maintenance window"
            if window
            else "without a maintenance window"
            if window is False
            else ""
        )
    if event == "backup.succeeded":
        return str(entry.get("backup_id"))
    if event == "backup.failed":
        return str(entry.get("error") or "no reason recorded")
    if event == "cutover.succeeded":
        return "setup:upgrade ran" if entry.flag("setup_upgrade_ran") else ""
    if event == "warmup.completed":
        ok, asked, percent = entry.get("ok"), entry.get("requested"), entry.get("percent")
        return f"{ok} of {asked} pages answered ({percent}%)"
    if event == "deploy.finished":
        return str(entry.get("outcome"))
    if event == "deploy.verified":
        return str(entry.get("outcome"))
    return ""


def _who_deployed(d: Deployment) -> Answer:
    actor = d.deployer
    if not actor.known:
        return Answer(
            "Who deployed it?",
            "Not recorded",
            "The first record carries no identity.",
            language.ATTENTION,
        )
    return Answer("Who deployed it?", actor.name, actor.context)


def _who_approved(d: Deployment) -> Answer:
    approval = d.approval
    if approval is None:
        return Answer(
            "Who approved it?",
            "No approval on record",
            "This environment may not require one, or the deploy stopped before it was checked.",
            language.UNKNOWN,
        )
    return Answer(
        "Who approved it?",
        approval.signer,
        f"Signed tag {approval.tag}, key {approval.signing_key}",
        exact=(approval.signing_key,),
    )


def _what_went_out(d: Deployment) -> Answer:
    commit = d.commit
    branch = str(d.start.get("branch") or "")
    if not commit:
        return Answer(
            "What went out?",
            f"Release {d.release}" if d.release else "Not recorded",
            f"From {branch}. No build was recorded." if branch else "No build was recorded.",
            language.UNKNOWN,
        )
    detail = [f"from {branch}" if branch else "", f"release {d.release}"]
    if d.artefact:
        detail.append(f"archive SHA-256 {_short(d.artefact, 16)}…")
    builder = d.build.get("builder") if d.build else ""
    if builder:
        detail.append(f"built on {builder}")
    return Answer(
        "What went out?",
        f"Commit {_short(commit)}",
        _sentence_case(", ".join(p for p in detail if p)),
        exact=tuple(v for v in (commit, d.artefact) if v),
    )


def _same_thing(d: Deployment) -> Answer:
    question = "Is it what was approved and built?"
    approved, archived = d.approved_commit_matches, d.artefact_matches
    if approved is False:
        return Answer(
            question,
            "No",
            "The approved commit is not the commit that was built.",
            language.PROBLEM,
        )
    if archived is False:
        return Answer(
            question,
            "No",
            "The archive cut over is not the archive that was built.",
            language.PROBLEM,
        )
    said = []
    if approved:
        said.append("the approved commit is the one built")
    if archived:
        said.append("the archive cut over has the checksum recorded at build")
    if said:
        return Answer(question, "Yes", _sentence_case("; ".join(said)) + ".")
    return Answer(
        question,
        "Cannot tell",
        "The records needed to compare are not all there.",
        language.UNKNOWN,
    )


def _when_it_ran(d: Deployment) -> Answer:
    started = moment(d.started_at)
    if d.finished is None:
        return Answer(
            "When?",
            f"Started {started}",
            f"Last step recorded: {language.ledger_step(d.last_step.event).lower()}",
        )
    parts = [
        f"{language.span_name(key).lower()} {spoken(d.span(key))}"
        for key in ("build", "cutover")
        if d.span(key) is not None
    ]
    detail = f"Took {spoken(d.duration_s)}."
    return Answer("When?", f"Started {started}", f"{detail} {text.sentence(parts).capitalize()}.")


def _downtime(d: Deployment) -> Answer:
    question = "Did the site go into maintenance?"
    window = d.maintenance_window
    if window:
        held = spoken(d.span(HEADLINE))
        shown = (
            f"The maintenance page showed for {held}, while the database or configuration changed."
            if held
            else "The database or configuration needed changing, so the maintenance page showed."
        )
        return Answer(question, f"Yes, for {held}" if held else "Yes", shown, language.ATTENTION)
    if window is False:
        return Answer(question, "No", "Nothing needed a window, so the site stayed up.")
    if d.maintenance_planned:
        return Answer(
            question,
            "No",
            "One was planned, but the deploy stopped before the maintenance page went up.",
        )
    return Answer(
        question, "No", "The deploy stopped before the cutover, so nothing changed on the site."
    )


BACKUP_REASONS = {
    "window": "Taken because this release needed a maintenance window",
    "always": "Taken because this environment backs up on every deploy",
}


def _backup(d: Deployment) -> Answer:
    question = "Was there a backup?"
    failed, taken = d.backup_failed, d.backup
    if failed is not None:
        error = str(failed.get("error") or "No reason was recorded.")
        return Answer(question, "It failed", error, language.PROBLEM)
    if taken is not None:
        reason = str(taken.get("reason") or "")
        backup_id = str(taken.get("backup_id"))
        return Answer(question, backup_id, BACKUP_REASONS.get(reason, ""), exact=(backup_id,))
    if d.first("cutover.started") is None:
        return Answer(
            question,
            "None recorded",
            "The deploy stopped before the backup step.",
            language.UNKNOWN,
        )
    return Answer(question, "None taken", "This environment's backup rule did not call for one.")


def _did_it_work(d: Deployment) -> Answer:
    word = language.ledger_outcome(d.outcome)
    level = {
        SUCCEEDED: language.OK,
        BUILT_ONLY: language.OK,
        STOPPED: language.PROBLEM,
        FAILED: language.PROBLEM,
    }.get(d.outcome, language.ATTENTION)
    detail = word.meaning
    warm = d.warmup
    if warm is not None:
        detail = f"{detail} Warm-up: {warm.get('ok')} of {warm.get('requested')} pages answered."
    if d.outcome == UNFINISHED:
        last = language.ledger_step(d.last_step.event).lower()
        detail = f"{detail} It stopped after {last}, or it is still running."
    return Answer("Did it work?", word.name, detail, level)


def _checked_since(d: Deployment) -> Answer:
    verified = d.verified
    if verified is None:
        return Answer(
            "Has anyone checked it since?",
            "Not verified",
            "The checks after a deploy have not passed for this release.",
            language.UNKNOWN,
        )
    return Answer(
        "Has anyone checked it since?",
        f"Yes, {verified.actor.name}" if verified.actor.known else "Yes",
        f"Passed {moment(verified.at)}",
    )


def _trust(d: Deployment, chain: Chain) -> Answer:
    question = "Can these records be trusted?"
    if not d.trusted:
        return Answer(
            question,
            "No",
            f"The chain breaks at line {chain.broken_line}: {chain.reason}. "
            "Some of this deploy's records sit after the break.",
            language.PROBLEM,
        )
    if chain.state == BROKEN:
        return Answer(
            question,
            "Yes, these ones",
            f"They sit before the break at line {chain.broken_line}, so they link to the start.",
            language.ATTENTION,
        )
    return Answer(
        question,
        "Yes",
        f"All {len(chain.entries)} records link back to the start. Head {_short(chain.head, 16)}…",
        exact=(chain.head,),
    )


@dataclass(frozen=True)
class Book:
    """One ledger as a front end shows it: where it came from, its chain, its deploys."""

    source: Source
    chain: Chain
    deployments: list[Deployment]

    @property
    def environment(self) -> str:
        return self.chain.environment or self.source.environment

    @property
    def timings(self) -> list[Timing]:
        """How long the deploys in this ledger take, measured from their own records."""
        return timings(self.deployments)


def gather(repo: Path, declared: list[str], given: list[Path] | None = None) -> list[Book]:
    """Every ledger this control plane has, read and grouped, the most recently deployed first."""
    books = []
    for source in locate(repo, declared, given):
        chain = read(source.path, source.environment)
        books.append(Book(source=source, chain=chain, deployments=deployments(chain)))
    return sorted(books, key=_newest, reverse=True)


def _newest(book: Book) -> str:
    return book.deployments[0].started_at if book.deployments else ""


def find(books: list[Book], release: str) -> tuple[Book, Deployment] | None:
    """The newest deploy of a release, or the newest deploy anywhere for `last`."""
    candidates = [
        (book, deployment)
        for book in books
        for deployment in book.deployments
        if release == "last" or deployment.release == release
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda pair: pair[1].started_at)


@dataclass(frozen=True)
class Timing:
    """How long one span usually takes here, and how much it varies."""

    key: str
    name: str
    meaning: str
    samples: int = 0
    typical: float = 0.0
    fastest: float = 0.0
    slowest: float = 0.0
    # Why there is nothing to show. A span with no sample says so; it never
    # reports zero, which would read as a deploy that took no time at all.
    blocked: str = ""

    @property
    def measured(self) -> bool:
        return self.samples > 0


NOTHING_TIMED = {
    "maintenance": "No deploy here has needed a maintenance window.",
    "to_verify": "Nothing here has been verified after the deploy.",
}

NOT_REACHED = "No deploy here has recorded both ends of this."


def timings(deployments: list[Deployment]) -> list[Timing]:
    """The spans across a ledger's deploys, each either measured or saying why not."""
    found = []
    for key in SPAN_RECORDS:
        seconds = sorted(
            value
            for deployment in deployments
            if deployment.trusted
            for span_key, value in deployment.spans.items()
            if span_key == key
        )
        word = language.SPANS[key]
        if not seconds:
            found.append(
                Timing(
                    key=key,
                    name=word.name,
                    meaning=word.meaning,
                    blocked=NOTHING_TIMED.get(key, NOT_REACHED),
                )
            )
            continue
        found.append(
            Timing(
                key=key,
                name=word.name,
                meaning=word.meaning,
                samples=len(seconds),
                typical=_median(seconds),
                fastest=seconds[0],
                slowest=seconds[-1],
            )
        )
    return found


def spoken(seconds: float | None) -> str:
    """`under a second` for a span measured as zero; nothing at all for one not measured.

    The difference matters: an empty string means the ledger cannot say, and
    zero means it can and the step was that fast.
    """
    if seconds is None:
        return ""
    return took(seconds) or "under a second"


def _median(values: list[float]) -> float:
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2
