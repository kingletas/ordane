"""A policy refusal has to mean the same thing on every front end.

`policy.clean_tree` and `policy.refs` are safety refusals somebody relies on,
and for a long time only the desktop window applied them. `ordane run` from a
terminal went straight past. A policy enforced on one surface and not another
is worse than no policy at all, because it is the one people trust.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ordane.core import runbook

ROOT = Path(__file__).resolve().parents[1]

# Every front end that can start a run. The web one launches through the same
# CLI-shaped path, so these two are where a launch is decided.
LAUNCHERS = (
    ROOT / "src" / "ordane" / "cli.py",
    ROOT / "src" / "ordane" / "desktop" / "window.py",
)


def calls_refusals(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "refusals":
            return True
    return False


def test_every_front_end_that_launches_applies_the_policy():
    missing = [path.name for path in LAUNCHERS if not calls_refusals(path)]
    assert missing == [], f"these can start a run without checking the policy: {missing}"


def a_runbook(**policy) -> runbook.Runbook:
    return runbook.read("deploy", {"policy": policy})


def test_a_branch_outside_the_list_is_refused():
    refused = runbook.refusals(a_runbook(refs=["main"]), hosts=1, ref="wip", dirty=False)
    assert [one.reason for one in refused]


def test_no_branch_at_all_is_refused_too():
    """A directory that is not a checkout has no ref, and `refs:` cannot be
    satisfied by the absence of the thing it constrains."""
    refused = runbook.refusals(a_runbook(refs=["main"]), hosts=1, ref="", dirty=False)
    assert refused and "no branch" in refused[0].reason


def test_a_dirty_tree_is_refused():
    refused = runbook.refusals(a_runbook(clean_tree=True), hosts=1, ref="main", dirty=True)
    assert [one.reason for one in refused]


def test_too_many_hosts_is_refused():
    refused = runbook.refusals(a_runbook(max_hosts=2), hosts=9, ref="main", dirty=False)
    assert refused and "9" in refused[0].reason


def test_every_broken_policy_is_reported_at_once():
    """Fixing one and being refused again is how somebody stops reading."""
    refused = runbook.refusals(
        a_runbook(refs=["main"], clean_tree=True, max_hosts=2),
        hosts=9,
        ref="wip",
        dirty=True,
    )
    assert len(refused) == 3


def test_a_runbook_with_no_policy_refuses_nothing():
    assert runbook.refusals(a_runbook(), hosts=99, ref="anything", dirty=True) == []
