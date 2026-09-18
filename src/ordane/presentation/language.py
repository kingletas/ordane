"""The words a person reads, in one place, so no front end invents its own.

Every identifier this tool works with: a danger level, a run state, the key of
a delivery measure: has an English name and a sentence saying what it means.
The desktop app, the web pages and the terminal all read them from here, which
is what stops one surface calling something `high` while another calls it a
cutover.
"""

from __future__ import annotations

from dataclasses import dataclass

# The four verdicts, worst last. They live here rather than beside the judging
# so that a module which only needs the words does not import the whole engine.
# What stands in for a secret wherever one would otherwise be written down.
# It lives here rather than with the redactor because it is a word a person
# reads, and because everything that masks has to agree on it.
MASK = "[redacted]"

OK = "ok"
ATTENTION = "attention"
PROBLEM = "problem"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Word:
    """One machine value, said in English twice: short, then in full."""

    name: str
    meaning: str


# What a target's `danger:` level actually means for the people using the site.
# `low` is deliberately unnamed: a badge on everything is a badge on nothing.
DANGER = {
    "low": Word("", "Reads state, or changes nothing a customer would notice."),
    "medium": Word("Changes the hosts", "This changes something on the hosts it reaches."),
    "high": Word("Customers see this", "This changes what customers see."),
}

# The state a run ended in. `running` is the only one that is not an outcome.
STATE = {
    "running": Word("Running", "Still going. The output below is arriving live."),
    "succeeded": Word("Succeeded", "Finished with exit code 0."),
    "failed": Word("Failed", "Finished with a non-zero exit code."),
    "error": Word("Could not start", "The command never ran: see the reason below."),
    "cancelled": Word("Cancelled", "Stopped from here before it finished."),
}

# The four delivery measures, under the names the industry gave them.
#
# These were written as questions: "How often we release", and changed back:
# the reader here is the person who runs the deploys, the DORA names are what
# they already call these, and a term of art restated as a question is less
# precise, not friendlier. The plain sentence is still written, next to the
# name rather than instead of it.
MEASURE = {
    "cadence": Word("Release frequency", "Production releases per month, from the release log."),
    "lead_time": Word(
        "Lead time for changes",
        "Median time from a release being built to it reaching production.",
    ),
    "failure_rate": Word(
        "Change failure rate",
        "Share of recorded deploys that failed or were rolled back.",
    ),
    "recovery": Word(
        "Time to restore",
        "Median time from a deploy that failed to the next one that worked.",
    ),
}

# The verdict, as the one word a status card leads with.
VERDICT = {
    OK: Word("All clear", "Every check this console can make came back clean."),
    ATTENTION: Word("Needs attention", "Something is degraded but nothing is broken."),
    PROBLEM: Word("Action required", "Something failed, or an objective is being missed."),
    UNKNOWN: Word("Waiting on you", "Healthy so far as it can be seen, which is not everything."),
}

# What a measure with no source is short of, written as the thing to do about
# it rather than as the absence. Nothing here promises a button: this console
# connects to no incident tracker and installs no probe, and a call to action
# that opens nothing is worse than a sentence that says what is missing.
NEEDS = {
    "cadence": "A release history. The reporter writes one; `make dora` in the control plane.",
    "lead_time": "Lead-time figures in the release history, which the reporter fills in.",
    "failure_rate": "Deploy runs launched from this console, so a failure can be counted.",
    "recovery": "A deploy run that failed, and a later one that succeeded. It is the deployment "
    "this restores, not the service: nothing here reads an incident tracker.",
}


def measure_needs(key: str) -> str:
    """What would fill this measure, or an empty string if nothing is known to."""
    return NEEDS.get(key, "")


def danger_badge(level: str) -> str:
    """The short label for a danger level, or an empty string for the harmless ones."""
    return DANGER.get(level, DANGER["low"]).name


def danger_note(level: str) -> str:
    """The full sentence shown before a run is launched."""
    return DANGER.get(level, DANGER["low"]).meaning


def state_name(state: str) -> str:
    return STATE[state].name if state in STATE else state.capitalize()


def state_meaning(state: str) -> str:
    return STATE[state].meaning if state in STATE else ""


def measure_name(key: str, fallback: str = "") -> str:
    return MEASURE[key].name if key in MEASURE else (fallback or key)


def measure_meaning(key: str) -> str:
    return MEASURE[key].meaning if key in MEASURE else ""


# Never shortened to `plane` in front of anybody. That word is the key a shared
# history is scoped on, and the rail had abbreviated it on one row.
PLANE = "control plane"

# The checks a control plane declares about itself, which are not the checkup.
# One runs the repository's own tests; the other examines how it is set up, and
# they were called the same thing in three places.
OWN_CHECKS = f"this {PLANE}'s own checks"

# What each kind of run is, said rather than spelled. A history several people
# read should not ask them to know what `postcheck` means here.
RUN_KINDS = {
    "target": "the operation",
    "checks": OWN_CHECKS,
    "precheck": "checked first",
    "postcheck": "checked afterwards",
    "probe": "a question asked of the hosts",
}


def run_kind(kind: str) -> str:
    return RUN_KINDS.get(kind, kind or "a run")


# The steps a deploy ledger records, in the order a deploy walks through them.
LEDGER_STEPS = {
    "deploy.started": Word("Deploy requested", "Somebody started the deploy playbook."),
    "approval.verified": Word(
        "Approval checked",
        "The commit carries a signed approval from someone other than the deployer.",
    ),
    "build.succeeded": Word("Built", "The release was built and its archive checksummed."),
    "cutover.started": Word("Cutover began", "The web hosts started switching to the new release."),
    "backup.succeeded": Word("Backed up", "The database was backed up before anything changed."),
    "backup.failed": Word(
        "Backup failed",
        "The backup did not complete, so the deploy stopped with the old release live.",
    ),
    "maintenance.enabled": Word(
        "Maintenance on", "The site showed its maintenance page while the database changed."
    ),
    "cutover.succeeded": Word("Went live", "The new release is the one serving the site."),
    "warmup.completed": Word(
        "Caches warmed", "The storefront pages were requested to fill the caches."
    ),
    "deploy.finished": Word("Finished", "The deploy playbook reached its end."),
    "deploy.verified": Word(
        "Verified", "The checks after a deploy ran against the live release and passed."
    ),
}

LEDGER_OUTCOMES = {
    "succeeded": Word("Live", "The deploy finished and the release went live."),
    "built-only": Word(
        "Built, not live", "The deploy finished without making the release live, as asked."
    ),
    "finished": Word("Finished", "The deploy finished. Its own record does not say how it went."),
    "failed": Word("Did not succeed", "The deploy finished and its record says it did not work."),
    "records": Word(
        "Records only",
        "Records with no deploy behind them in this ledger: nothing here opened a deploy.",
    ),
    "stopped": Word(
        "Stopped",
        "The deploy stopped itself before the release went live, so the old one kept serving.",
    ),
    "unfinished": Word("No finish recorded", "The ledger has no finish for this deploy."),
}

CHAIN_STATES = {
    "intact": Word(
        "Chain intact",
        "Every record links to the one before it, so none was edited, removed or reordered.",
    ),
    "broken": Word(
        "Chain broken",
        "A record does not link to the one before it. Nothing from that line on can be trusted.",
    ),
    "empty": Word("No deploys yet", "The ledger exists and holds no records."),
    "missing": Word("No ledger here", "Nothing has been written to this path yet."),
    "unreadable": Word("Cannot be read", "The file is there but could not be read."),
}


def ledger_step(event: str) -> str:
    return LEDGER_STEPS[event].name if event in LEDGER_STEPS else event


def ledger_step_meaning(event: str) -> str:
    return LEDGER_STEPS[event].meaning if event in LEDGER_STEPS else ""


def ledger_outcome(outcome: str) -> Word:
    return LEDGER_OUTCOMES.get(outcome, Word(outcome, ""))


def newer_format(version: int) -> str:
    """What to say about a ledger written in a format newer than this reader knows."""
    return (
        f"Written in format {version}, which is newer than this reader knows. "
        "What it can read is shown; a field it does not know is left out, so take "
        "an empty one here as unread rather than as absent."
    )


def chain_state(state: str) -> Word:
    return CHAIN_STATES.get(state, Word(state, ""))


# The spans a ledger can be asked for, each measured between two records it
# already carries. Nothing here times a phase with only one record.
SPANS = {
    "maintenance": Word(
        "Maintenance window",
        "How long the site showed its maintenance page: the only span customers experience.",
    ),
    "cutover": Word(
        "Cutover", "From the cutover starting to the new release being the one that serves."
    ),
    "build": Word("Build", "From the deploy being asked for to the archive being built."),
    "total": Word("Whole deploy", "From the request to the playbook finishing."),
    "warmup": Word("Warm-up", "From the release going live to the storefront caches being filled."),
    "to_verify": Word(
        "Wait to verify", "From the deploy finishing to the checks after it passing."
    ),
}


def span_name(key: str) -> str:
    return SPANS[key].name if key in SPANS else key


def span_meaning(key: str) -> str:
    return SPANS[key].meaning if key in SPANS else ""
