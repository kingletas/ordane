"""The operational half of a target, and what it refuses.

Everything here is declared. A precheck nobody named does not run and a
recovery nobody wrote is not offered: an undo that is assumed is worse than
one that is absent, because somebody plans around it.
"""

from datetime import date

from ordane.core import runbook

TODAY = date(2026, 9, 5)


def test_a_target_that_declares_nothing_has_a_runbook_that_asks_for_nothing():
    plain = runbook.read("ping", {})
    assert not plain.documented
    assert not plain.policy.any
    assert plain.condition(TODAY) == "unowned"
    assert runbook.refusals(plain, hosts=900, ref="anything", dirty=True) == []


def test_owned_and_looked_at_recently_is_owned():
    read = runbook.read("deploy", {"owner": "platform", "reviewed": "2026-06-01"})
    assert read.condition(TODAY) == "owned"
    assert not read.stale(TODAY)


def test_a_year_without_a_look_is_stale():
    read = runbook.read("deploy", {"owner": "platform", "reviewed": "2025-09-05"})
    assert read.stale(TODAY)
    assert read.condition(TODAY) == "stale"


def test_never_reviewed_is_unowned_rather_than_stale():
    """Stale means somebody looked and stopped. Nobody looking is a different gap."""
    read = runbook.read("deploy", {"owner": "platform"})
    assert not read.stale(TODAY)
    assert read.condition(TODAY) == "unowned"


def test_a_review_date_that_is_not_a_date_is_ignored_rather_than_believed():
    assert not runbook.read("deploy", {"reviewed": "last tuesday"}).stale(TODAY)


# --- what a policy refuses ---


def _policed(**policy) -> runbook.Runbook:
    return runbook.read("deploy", {"policy": policy})


def test_a_run_that_reaches_more_hosts_than_the_policy_allows_is_refused():
    refused = runbook.refusals(_policed(max_hosts=5), hosts=9, ref="main", dirty=False)
    assert len(refused) == 1
    assert "9 hosts" in refused[0].reason and "allows 5" in refused[0].reason


def test_exactly_the_limit_is_allowed():
    assert runbook.refusals(_policed(max_hosts=5), hosts=5, ref="main", dirty=False) == []


def test_a_ref_family_is_matched_the_way_a_control_plane_names_one():
    policy = _policed(refs=["main", "release/*"])
    for ref in ("main", "release/2026-09"):
        assert runbook.refusals(policy, hosts=1, ref=ref, dirty=False) == []
    assert runbook.refusals(policy, hosts=1, ref="feature/x", dirty=False)


def test_a_detached_head_is_not_one_of_the_refs():
    assert runbook.refusals(_policed(refs=["main"]), hosts=1, ref="", dirty=False)


def test_a_dirty_tree_is_refused_where_the_policy_says_so():
    assert runbook.refusals(_policed(clean_tree=True), hosts=1, ref="main", dirty=True)
    assert runbook.refusals(_policed(clean_tree=True), hosts=1, ref="main", dirty=False) == []


def test_every_broken_policy_is_reported_rather_than_the_first():
    """Fixing one and being refused again is how a person stops reading the reason."""
    refused = runbook.refusals(
        _policed(max_hosts=1, refs=["main"], clean_tree=True),
        hosts=9,
        ref="feature/x",
        dirty=True,
    )
    assert len(refused) == 3


def test_a_policy_written_wrongly_asks_for_nothing_rather_than_everything():
    """A threshold that will not parse must not become a refusal nobody can satisfy."""
    read = runbook.read("deploy", {"policy": {"max_hosts": "lots", "refs": "main"}})
    assert read.policy.max_hosts == 0
    assert read.policy.refs == ()
    assert runbook.refusals(read, hosts=900, ref="x", dirty=True) == []


def test_a_target_whose_spec_is_not_a_mapping_does_not_raise():
    assert runbook.read("deploy", "nonsense").target == "deploy"
    assert runbook.read("deploy", None).owner == ""


# --- the sequence a runbook actually runs ---


def test_a_runbook_with_no_checks_is_one_step():
    assert [s.kind for s in runbook.steps(runbook.read("ping", {}))] == ["operation"]


def test_the_checks_go_around_the_operation_in_order():
    book = runbook.read("deploy", {"precheck": "check", "postcheck": "verify"})
    assert [(s.kind, s.target) for s in runbook.steps(book)] == [
        ("precheck", "check"),
        ("operation", "deploy"),
        ("postcheck", "verify"),
    ]


def test_a_precheck_that_fails_stops_the_operation_from_running():
    book = runbook.read("deploy", {"precheck": "check", "postcheck": "verify"})
    assert runbook.after(book, "precheck", ok=False) is None
    assert runbook.after(book, "precheck", ok=True).target == "deploy"


def test_an_operation_that_failed_does_not_run_its_postcheck():
    """A postcheck proves a change worked; asking it about one that did not is noise."""
    book = runbook.read("deploy", {"postcheck": "verify"})
    assert runbook.after(book, "operation", ok=False) is None
    assert runbook.after(book, "operation", ok=True).target == "verify"


def test_the_last_step_is_followed_by_nothing():
    book = runbook.read("deploy", {"precheck": "check"})
    assert runbook.after(book, "operation", ok=True) is None


def test_a_step_that_is_not_in_this_runbook_leads_nowhere():
    assert runbook.after(runbook.read("deploy", {}), "postcheck", ok=True) is None


# --- the control plane's own checks, as the first step ---


def test_the_declared_checks_run_before_everything_else():
    book = runbook.read("deploy", {"validate": True, "precheck": "check", "postcheck": "verify"})
    assert [s.kind for s in runbook.steps(book)] == [
        "validate",
        "precheck",
        "operation",
        "postcheck",
    ]


def test_checks_that_fail_stop_the_precheck_as_well_as_the_deploy():
    book = runbook.read("deploy", {"validate": True, "precheck": "check"})
    assert runbook.after(book, "validate", ok=False) is None
    assert runbook.after(book, "validate", ok=True).target == "check"


def test_a_runbook_that_does_not_ask_for_them_does_not_run_them():
    assert [s.kind for s in runbook.steps(runbook.read("deploy", {}))] == ["operation"]


def test_the_validate_step_names_no_target_because_it_is_not_one():
    step = runbook.steps(runbook.read("deploy", {"validate": True}))[0]
    assert step.target == ""
    assert "own checks" in step.sentence


# --- which runbooks lean on a target, which is worth knowing before changing it ---


TARGETS = {
    "deploy": {"precheck": "check", "postcheck": "check", "recovery": "maintenance-off"},
    "activate": {"precheck": "check"},
    "check": {},
    "maintenance-off": {},
    "ping": {},
}


def test_a_target_three_runbooks_lean_on_says_so():
    uses = runbook.used_by(TARGETS, "check")
    assert [(one.target, one.role) for one in uses] == [
        ("activate", "precheck"),
        ("deploy", "postcheck"),
        ("deploy", "precheck"),
    ]


def test_a_target_nobody_calls_has_nothing_leaning_on_it():
    assert runbook.used_by(TARGETS, "ping") == []


def test_a_recovery_is_a_use_like_any_other():
    assert [one.role for one in runbook.used_by(TARGETS, "maintenance-off")] == ["recovery"]


def test_a_runbook_does_not_count_as_leaning_on_itself():
    assert runbook.used_by({"a": {"precheck": "a"}}, "a") == []


def test_each_use_says_what_it_is_in_words():
    said = {one.sentence for one in runbook.used_by(TARGETS, "check")}
    assert "deploy: checks with this first" in said
    assert "deploy: proves itself with this" in said


def test_nothing_declared_leans_on_nothing():
    assert runbook.used_by({}, "check") == []
    assert runbook.used_by(None, "check") == []
    assert runbook.used_by(TARGETS, "") == []


def test_a_target_names_the_playbook_it_runs_rather_than_it_being_guessed():
    """A recipe can call anything; guessing which playbook it meant reads the wrong file."""
    assert runbook.read("deploy", {"playbook": "actions/deployment.yml"}).playbook == (
        "actions/deployment.yml"
    )
    assert runbook.read("deploy", {}).playbook == ""
