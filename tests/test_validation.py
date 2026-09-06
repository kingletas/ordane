"""Checks a control plane runs against itself, in a container it declares.

**Not an execution node.** The running stays on this machine; what the
container pins is which Ansible, which collections, which Python. The
properties that matter are that it reaches nothing and writes nothing.
"""

from pathlib import Path

import pytest

from ordane.core import validation


def _suite(**raw) -> validation.Suite:
    return validation.read({"image": "an/image:1", "checks": [{"run": ["true"]}], **raw})


# --- what a control plane declared ---


def test_a_suite_is_read_from_the_configuration():
    suite = validation.read(
        {
            "image": "ghcr.io/ansible/creator-ee:v25.1.0",
            "checks": [
                {"name": "Syntax", "run": ["ansible-playbook", "--syntax-check", "site.yml"]},
                {"run": ["ansible-lint"]},
            ],
        }
    )
    assert suite.declared
    assert [c.name for c in suite.checks] == ["Syntax", "ansible-lint"]
    assert suite.checks[0].argv[0] == "ansible-playbook"


def test_a_check_with_nothing_to_run_is_not_a_check():
    for entry in ({"name": "empty"}, {"run": []}, {"run": "a string"}, "not a mapping"):
        assert validation.read({"image": "x", "checks": [entry]}).checks == ()


def test_nothing_declared_is_an_empty_suite_rather_than_an_error():
    for raw in (None, {}, "nonsense", []):
        assert not validation.read(raw).declared


# --- why it cannot run, which is never why a deploy cannot ---


def test_no_image_and_no_checks_each_say_so():
    assert "image" in validation.available(validation.read({"checks": [{"run": ["true"]}]}))
    assert "checks" in validation.available(validation.read({"image": "an/image:1"}))


@pytest.mark.parametrize("image", ["-v/etc:/etc", "an image", "", "a/b" * 200])
def test_an_image_reference_a_registry_would_not_write_is_refused(image):
    assert validation.available(validation.read({"image": image, "checks": [{"run": ["true"]}]}))


def test_a_missing_container_engine_is_named_rather_than_blamed_on_the_repository():
    suite = _suite(engine=["definitely-not-installed"])
    assert "definitely-not-installed" in validation.available(suite)


# --- the invocation, which is where the safety is ---


def test_the_container_reaches_nothing_writes_nothing_and_is_not_root():
    argv = validation.argv_for(Path("/repo"), _suite(), validation.Check("x", ("echo", "hi")))
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert f"/repo:{validation.WORKDIR}:ro" in argv
    assert "--user" in argv and not argv[argv.index("--user") + 1].startswith("0:")
    assert "--privileged" not in argv
    assert "/var/run/docker.sock" not in " ".join(argv)


def test_the_image_is_separated_from_the_flags_by_a_double_dash():
    """So an image reference can never be read as an option, however it got here."""
    argv = validation.argv_for(Path("/repo"), _suite(), validation.Check("x", ("echo",)))
    assert argv[argv.index("--") + 1] == "an/image:1"


def test_the_check_is_an_argument_list_rather_than_a_shell_string():
    argv = validation.argv_for(
        Path("/repo"), _suite(), validation.Check("x", ("sh", "-c", "echo hi"))
    )
    assert argv[-3:] == ["sh", "-c", "echo hi"]


# --- the report ---


def test_a_suite_that_cannot_run_reports_why_and_runs_nothing(tmp_path):
    report = validation.run(tmp_path, validation.read({"image": "x"}))
    assert not report.ok
    assert report.results == []
    assert "checks" in report.error


def test_a_report_counts_what_passed():
    report = validation.Report(
        results=[
            validation.Result(validation.Check("a", ("true",)), ok=True),
            validation.Result(validation.Check("b", ("false",)), ok=False),
        ]
    )
    assert not report.ok
    assert report.summary == "1 of 2 passed"
    assert [one.check.name for one in report.failed] == ["b"]
    assert [one.state for one in report.results] == ["passed", "failed"]


def test_an_engine_written_as_a_string_is_the_engine_that_runs():
    """`engine: podman` is how a person writes it, and it used to be discarded.

    Only a list was read, so a string fell through to the docker default and
    said nothing. Asking for one container engine and silently getting another
    is the kind of quiet substitution nobody checks for.
    """
    suite = validation.read({"image": "x", "checks": [{"run": "true"}], "engine": "podman"})
    assert suite.engine == ("podman",)


def test_an_engine_string_carrying_flags_is_split_the_way_a_shell_would():
    suite = validation.read(
        {"image": "x", "checks": [{"run": "true"}], "engine": "podman --remote"}
    )
    assert suite.engine == ("podman", "--remote")


def test_a_list_engine_still_reads_as_it_did():
    suite = validation.read(
        {"image": "x", "checks": [{"run": "true"}], "engine": ["docker", "--rm"]}
    )
    assert suite.engine == ("docker", "--rm")


def test_an_engine_of_the_wrong_shape_falls_back_rather_than_running_nothing():
    suite = validation.read({"image": "x", "checks": [{"run": "true"}], "engine": 7})
    assert suite.engine == validation.DEFAULT_ENGINE
