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
    UNKNOWN: Word("Setup needed", "Healthy so far as it can be seen, which is not everything."),
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
