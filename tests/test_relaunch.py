from ordane.insight import relaunch
from ordane.presentation.language import MASK
from ordane.record.store import Run

RECAP = """
PLAY RECAP *********************************************************************
web01 : ok=3 changed=1 unreachable=0 failed=0 skipped=0
web02 : ok=1 changed=0 unreachable=0 failed=1 skipped=0
web03 : ok=0 changed=0 unreachable=1 failed=0 skipped=0
"""


def a_run(argv=None, summary=None) -> Run:
    from ordane.record.summary import parse

    return Run(
        id="x",
        kind="target",
        name="deploy",
        environment="staging",
        params={},
        argv=argv if argv is not None else ["ansible-playbook", "-i", "inv", "p.yml"],
        command="",
        actor="test",
        started="2026-09-05T10:00:00Z",
        summary=(summary if summary is not None else parse(RECAP)).as_record(),
    )


def test_a_recorded_run_can_be_run_again_from_what_it_recorded():
    replay = relaunch.again(a_run())
    assert replay.possible
    assert replay.command.argv == ["ansible-playbook", "-i", "inv", "p.yml"]


def test_a_run_with_no_command_recorded_says_so_rather_than_running_nothing():
    replay = relaunch.again(a_run(argv=[]))
    assert not replay.possible
    assert "no command" in replay.refusal


def test_a_run_whose_command_was_masked_is_refused():
    """What was written down is not what ran, and the difference is the secret."""
    replay = relaunch.again(a_run(argv=["make", "x", f"token={MASK}"]))
    assert not replay.possible
    assert "secret" in replay.refusal


def test_the_failed_hosts_come_from_the_recap():
    assert relaunch.failed_hosts(a_run()) == ["web02", "web03"]


def test_an_unreachable_host_counts_as_one_that_failed():
    assert "web03" in relaunch.failed_hosts(a_run())


def test_relaunching_against_failures_limits_to_them():
    replay = relaunch.against_failures(a_run())
    assert replay.possible
    assert replay.command.argv[-2:] == ["--limit", "web02,web03"]
    assert replay.limited_to == ["web02", "web03"]


def test_an_existing_limit_is_replaced_rather_than_added_to():
    run = a_run(argv=["ansible-playbook", "--limit", "web01", "-i", "inv", "p.yml"])
    replay = relaunch.against_failures(run)
    assert replay.command.argv.count("--limit") == 1
    assert "web02,web03" in replay.command.argv


def test_a_clean_run_has_no_failures_to_limit_to():
    from ordane.record.summary import parse

    clean = parse("PLAY RECAP ***\nweb01 : ok=1 changed=0 unreachable=0 failed=0 skipped=0\n")
    replay = relaunch.against_failures(a_run(summary=clean))
    assert not replay.possible
    assert "no host failed" in replay.refusal


def test_a_make_run_is_refused_rather_than_handed_a_limit_it_may_ignore():
    replay = relaunch.against_failures(a_run(argv=["make", "deploy", "environment=staging"]))
    assert not replay.possible
    assert "make" in replay.refusal
