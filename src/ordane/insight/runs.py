"""Which runs a person is looking at, and what to call each group of them.

A history of sixty rows answers `what happened` badly. These are the four
questions actually asked of it: everything, what broke, what is still going,
what touched customers, and one place that answers them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

ALL = "all"
FAILED = "failed"
RUNNING = "running"
CUSTOMER = "customer"


@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    keep: Callable[[object], bool]
    empty: str


FILTERS = (
    Filter(ALL, "All runs", lambda run: True, "Nothing has run through this console yet."),
    Filter(
        FAILED,
        "Failed",
        lambda run: run.state in ("failed", "error"),
        "Nothing here has failed.",
    ),
    Filter(
        RUNNING,
        "Running",
        lambda run: run.state == "running",
        "Nothing is running right now.",
    ),
    Filter(
        CUSTOMER,
        "Customer-visible",
        lambda run: run.labels.get("cutover") == "true",
        "No cutover has run through this console.",
    ),
)


def by_key(key: str) -> Filter:
    return next((f for f in FILTERS if f.key == key), FILTERS[0])


def apply(runs: list, key: str) -> list:
    return [run for run in runs if by_key(key).keep(run)]
