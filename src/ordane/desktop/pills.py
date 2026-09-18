"""Which pill or tint the window draws each engine value in.

A mapping, not a widget: it names a CSS class for a chain state, an outcome or
a severity and touches no toolkit. That is what lets the check that every state
a reader can meet has a class run on a machine with no GTK installed, which is
where the gate runs.
"""

from __future__ import annotations

from ..insight import ledger
from ..presentation import language

OUTCOME_PILL = {
    ledger.SUCCEEDED: "ok",
    ledger.BUILT_ONLY: "ok",
    ledger.FINISHED: "wait",
    ledger.RECORDS_ONLY: "mute",
    ledger.FAILED: "fail",
    ledger.STOPPED: "fail",
    ledger.UNFINISHED: "warn",
}

LEVEL_TINT = {
    language.OK: ("tint-ok", "emblem-ok-symbolic"),
    language.ATTENTION: ("tint-warn", "dialog-warning-symbolic"),
    language.PROBLEM: ("tint-bad", "dialog-error-symbolic"),
    language.UNKNOWN: ("tint-muted", "dialog-question-symbolic"),
}

CHAIN_PILL = {
    ledger.INTACT: "ok",
    ledger.BROKEN: "fail",
    ledger.EMPTY: "mute",
    ledger.MISSING: "mute",
    ledger.UNREADABLE: "warn",
}
