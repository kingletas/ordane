"""The deploy ledger: its chain checked both ways, and its records turned into answers.

The fixture was written by the deploy playbook's own `bin/audit-log`, with
invented names, so the reader is held to the writer rather than to itself.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ordane import cli
from ordane.core import config as config_module
from ordane.insight import ledger
from ordane.presentation import language

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "written-by-audit-log.audit.jsonl"
HEAD = "9ef4ab87c602a8d5da84e7159e7b0e1857fa08d2f0fbbbaa246cbcde126ef234"

ALEX = {"git_email": "alex@example.com", "os_user": "alex", "control_host": "ops-laptop"}
PRIYA = {"git_email": "priya@example.com", "os_user": "priya", "control_host": "desk"}


def lines_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_chain(path: Path, payloads: list[dict]) -> Path:
    previous = ledger.GENESIS
    rows = []
    for seq, payload in enumerate(payloads, 1):
        stamp = f"2026-09-01T10:{seq:02d}:00Z"
        record = {"schema": 1, "seq": seq, "prev_hash": previous, "recorded_at": stamp, **payload}
        record["hash"] = ledger.record_hash(record)
        previous = record["hash"]
        rows.append(json.dumps(record, sort_keys=True))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def rewrite(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
    )


def event(name: str, release: str = "r1", actor: dict | None = None, **detail) -> dict:
    return {
        "event": name,
        "env_name": "staging",
        "release": release,
        "actor": actor or ALEX,
        **detail,
    }


def a_full_deploy(release: str = "r1", **overrides) -> list[dict]:
    commit, archive = "c" * 40, "a" * 64
    records = [
        event("deploy.started", release, branch="main", goes_live=True),
        event(
            "approval.verified",
            release,
            commit=commit,
            tag="approved/x",
            signer="sam@example.com",
            signing_key="SHA256:key",
        ),
        event("build.succeeded", release, commit=commit, artefact_sha256=archive, builder="b1"),
        event("cutover.started", release, maintenance_window=False, artefact_sha256=archive),
        event("cutover.succeeded", release, maintenance_window=False, setup_upgrade_ran=False),
        event("deploy.finished", release, outcome="success"),
    ]
    for record in records:
        record.update(overrides.get(record["event"], {}))
    return records


def answer(deployment, chain, question: str) -> ledger.Answer:
    return next(a for a in ledger.answers(deployment, chain) if a.question == question)


# --- the chain, against what the writer wrote ---


def test_a_ledger_the_playbook_wrote_verifies_here():
    chain = ledger.read(FIXTURE)
    assert chain.state == ledger.INTACT
    assert chain.head == HEAD
    assert len(chain.entries) == 9
    assert all(entry.trusted for entry in chain.entries)


def test_the_hash_is_the_writers_hash_for_every_record():
    for record in lines_of(FIXTURE):
        assert ledger.record_hash(record) == record["hash"]


def test_an_edited_field_breaks_the_chain_at_that_line(tmp_path):
    records = lines_of(FIXTURE)
    records[4]["backup_id"] = "db-snapshot-FAKE"
    path = tmp_path / "staging.audit.jsonl"
    rewrite(path, records)

    chain = ledger.read(path)
    assert chain.state == ledger.BROKEN
    assert chain.broken_line == 5
    assert "hash does not match" in chain.reason
    assert [e.trusted for e in chain.entries] == [True] * 4 + [False] * 5


def test_a_deleted_line_breaks_the_chain_where_it_was(tmp_path):
    records = lines_of(FIXTURE)
    del records[5]
    path = tmp_path / "staging.audit.jsonl"
    rewrite(path, records)

    chain = ledger.read(path)
    assert chain.state == ledger.BROKEN
    assert chain.broken_line == 6
    assert "expected 6" in chain.reason


def test_two_lines_swapped_break_the_chain(tmp_path):
    records = lines_of(FIXTURE)
    records[2], records[3] = records[3], records[2]
    path = tmp_path / "staging.audit.jsonl"
    rewrite(path, records)
    assert ledger.read(path).broken_line == 3


def test_a_record_rehashed_after_an_edit_still_breaks_the_next_link(tmp_path):
    """Recomputing an edited record's own hash is not enough to hide the edit."""
    records = lines_of(FIXTURE)
    records[1]["signer"] = "mallory@example.com"
    records[1]["hash"] = ledger.record_hash(records[1])
    path = tmp_path / "staging.audit.jsonl"
    rewrite(path, records)

    chain = ledger.read(path)
    assert chain.broken_line == 3
    assert "prev_hash" in chain.reason


@pytest.mark.parametrize(
    ("line", "reason"),
    [("", "blank line"), ("{not json", "not JSON"), ("[1, 2]", "not a JSON object")],
)
def test_a_line_that_is_not_a_record_breaks_the_chain(tmp_path, line, reason):
    path = tmp_path / "staging.audit.jsonl"
    text = FIXTURE.read_text(encoding="utf-8").splitlines()
    text.insert(3, line)
    path.write_text("\n".join(text) + "\n", encoding="utf-8")

    chain = ledger.read(path)
    assert chain.broken_line == 4
    assert reason in chain.reason


def test_a_missing_ledger_is_a_state_not_an_error(tmp_path):
    chain = ledger.read(tmp_path / "production.audit.jsonl")
    assert chain.state == ledger.MISSING
    assert chain.environment == "production"
    assert ledger.deployments(chain) == []


def test_an_empty_ledger_says_so(tmp_path):
    path = tmp_path / "staging.audit.jsonl"
    path.write_text("", encoding="utf-8")
    assert ledger.read(path).state == ledger.EMPTY


# --- the deploys in it ---


def test_the_fixture_reads_as_one_deploy_that_went_live():
    chain = ledger.read(FIXTURE)
    [deployment] = ledger.deployments(chain)
    assert deployment.outcome == ledger.SUCCEEDED
    assert deployment.deployer.name == "alex@example.com"
    assert deployment.approval.signer == "sam@example.com"
    assert deployment.maintenance_window is True
    assert deployment.artefact_matches is True
    assert deployment.approved_commit_matches is True


def test_an_intact_deploy_raises_no_problem(tmp_path):
    """The quiet direction: nothing wrong means nothing drawn as wrong."""
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", a_full_deploy()))
    [deployment] = ledger.deployments(chain)
    levels = {a.question: a.level for a in ledger.answers(deployment, chain)}
    assert language.PROBLEM not in levels.values()
    assert levels["Can these records be trusted?"] == language.OK


def test_every_deploy_is_its_own_attempt_newest_first(tmp_path):
    records = a_full_deploy("r1") + a_full_deploy("r2")
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    assert [d.release for d in ledger.deployments(chain)] == ["r2", "r1"]


def test_a_verify_joins_the_deploy_of_its_release_whoever_ran_it(tmp_path):
    records = [
        *a_full_deploy("r1"),
        *a_full_deploy("r2"),
        event("deploy.verified", "r1", actor=PRIYA, outcome="passed"),
    ]
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    newest, older = ledger.deployments(chain)
    assert newest.verified is None
    assert older.verified.actor.name == "priya@example.com"

    verify = ledger.steps(older)[-1]
    assert verify.role == "verified by"
    assert verify.who == "priya@example.com"
    assert verify.someone_else is True
    assert verify.worth_naming is True

    started, _approval, built, cutover = ledger.steps(older)[:4]
    assert (started.someone_else, started.worth_naming) == (False, True)
    assert (built.role, built.who, built.worth_naming) == ("built on", "b1", True)
    # A step the deployer took themselves names nobody: a name on every row
    # hides the row where somebody else acted.
    assert (cutover.someone_else, cutover.worth_naming) == (False, False)


def test_a_failed_backup_is_a_stopped_deploy_with_the_site_left_alone(tmp_path):
    records = [
        event("deploy.started", branch="main", goes_live=True),
        event("build.succeeded", commit="c", artefact_sha256="a", builder="b1"),
        event("cutover.started", maintenance_window=True, artefact_sha256="a"),
        event("backup.failed", reason="window", error="snapshot timed out"),
    ]
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    [deployment] = ledger.deployments(chain)

    assert deployment.outcome == ledger.STOPPED
    assert answer(deployment, chain, "Was there a backup?").level == language.PROBLEM
    assert answer(deployment, chain, "Was there a backup?").detail == "snapshot timed out"
    maintenance = answer(deployment, chain, "Did the site go into maintenance?")
    assert maintenance.answer == "No"
    assert "planned" in maintenance.detail


def test_a_deploy_with_no_finish_is_unfinished_and_names_its_last_step(tmp_path):
    records = a_full_deploy()[:4]
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    [deployment] = ledger.deployments(chain)
    assert deployment.outcome == ledger.UNFINISHED
    assert "cutover began" in answer(deployment, chain, "Did it work?").detail


def test_a_deploy_that_was_not_to_go_live_is_built_only(tmp_path):
    records = a_full_deploy(**{"deploy.started": {"goes_live": False}})
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    assert ledger.deployments(chain)[0].outcome == ledger.BUILT_ONLY


def test_an_archive_swapped_between_build_and_cutover_is_a_problem(tmp_path):
    records = a_full_deploy(**{"cutover.started": {"artefact_sha256": "b" * 64}})
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    [deployment] = ledger.deployments(chain)
    said = answer(deployment, chain, "Is it what was approved and built?")
    assert (said.answer, said.level) == ("No", language.PROBLEM)


def test_a_commit_built_that_was_not_the_one_approved_is_a_problem(tmp_path):
    records = a_full_deploy(**{"build.succeeded": {"commit": "d" * 40}})
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    [deployment] = ledger.deployments(chain)
    said = answer(deployment, chain, "Is it what was approved and built?")
    assert (said.answer, said.level) == ("No", language.PROBLEM)


def test_no_approval_is_unknown_rather_than_a_failure(tmp_path):
    records = [r for r in a_full_deploy() if r["event"] != "approval.verified"]
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    [deployment] = ledger.deployments(chain)
    said = answer(deployment, chain, "Who approved it?")
    assert said.level == language.UNKNOWN
    assert said.answer == "No approval on record"


def test_a_deploy_after_the_break_cannot_be_trusted(tmp_path):
    path = write_chain(tmp_path / "staging.audit.jsonl", a_full_deploy("r1") + a_full_deploy("r2"))
    records = lines_of(path)
    records[8]["actor"] = PRIYA
    rewrite(path, records)

    chain = ledger.read(path)
    newest, older = ledger.deployments(chain)
    assert answer(newest, chain, "Can these records be trusted?").level == language.PROBLEM
    assert answer(older, chain, "Can these records be trusted?").level == language.ATTENTION


def test_find_takes_a_release_or_the_newest(tmp_path):
    path = write_chain(tmp_path / "staging.audit.jsonl", a_full_deploy("r1"))
    later = a_full_deploy("r2")
    for record in later:
        record["recorded_at"] = "2026-09-02T09:00:00Z"
    other = write_chain(tmp_path / "docker.audit.jsonl", later)
    books = ledger.gather(tmp_path, [], [path, other])

    assert ledger.find(books, "r1")[1].release == "r1"
    assert ledger.find(books, "last")[1].release == "r2"
    assert ledger.find(books, "nope") is None


# --- where the ledgers are ---


def a_playbook(tmp_path: Path) -> Path:
    repo = tmp_path / "playbook"
    for name, path in (
        ("staging", "~/.local/state/deploy/staging.audit.jsonl"),
        ("docker", "{{ playbook_dir }}/local.d/audit/docker.audit.jsonl"),
        ("odd", "{{ state_root }}/odd.audit.jsonl"),
    ):
        vars_dir = repo / "inventory" / name / "group_vars"
        vars_dir.mkdir(parents=True)
        (vars_dir / "all.yml").write_text(f'audit:\n  path: "{path}"\n', encoding="utf-8")
    (repo / "inventory" / "bare" / "group_vars").mkdir(parents=True)
    (repo / "inventory" / "bare" / "group_vars" / "all.yml").write_text("x: 1\n", encoding="utf-8")
    return repo


def test_an_inventory_that_declares_its_ledger_is_read(tmp_path):
    repo = a_playbook(tmp_path)
    found = {s.environment: s for s in ledger.locate(repo, [])}

    assert set(found) == {"staging", "docker", "odd"}
    assert found["staging"].path == Path.home() / ".local/state/deploy/staging.audit.jsonl"
    assert found["docker"].path == repo / "local.d/audit/docker.audit.jsonl"
    assert found["staging"].origin == ledger.INVENTORY
    assert found["docker"].note == ""
    assert "template" in found["odd"].note


def test_a_declaration_replaces_discovery_and_a_flag_replaces_both(tmp_path):
    repo = a_playbook(tmp_path)
    (repo / "ledgers").mkdir()
    shutil.copy(FIXTURE, repo / "ledgers" / "staging.audit.jsonl")

    declared = ledger.locate(repo, ["ledgers/*.audit.jsonl"])
    assert [(s.environment, s.origin) for s in declared] == [("staging", ledger.CONFIG)]

    given = ledger.locate(repo, ["ledgers/*.audit.jsonl"], [FIXTURE])
    assert [(s.path, s.origin) for s in given] == [(FIXTURE, ledger.FLAG)]


def test_a_declared_path_that_does_not_exist_yet_is_still_listed(tmp_path):
    [source] = ledger.locate(tmp_path, ["state/production.audit.jsonl"])
    assert ledger.read(source.path).state == ledger.MISSING


def test_the_config_takes_one_path_or_a_list(tmp_path):
    config = tmp_path / config_module.CONFIG_NAME
    config.write_text("ledgers: ~/one.audit.jsonl\n", encoding="utf-8")
    assert config_module.load(tmp_path).ledgers == ["~/one.audit.jsonl"]

    config.write_text("ledgers: [a.jsonl, b.jsonl]\n", encoding="utf-8")
    assert config_module.load(tmp_path).ledgers == ["a.jsonl", "b.jsonl"]

    config.write_text("ledgers: {a: 1}\n", encoding="utf-8")
    with pytest.raises(config_module.ConfigError):
        config_module.load(tmp_path)


# --- the command ---


@pytest.fixture
def plane(tmp_path, monkeypatch) -> Path:
    """A control plane the command will accept, with its state kept out of the home folder."""
    monkeypatch.setattr(cli, "DEFAULT_STATE", tmp_path / "state")
    repo = tmp_path / "plane"
    repo.mkdir()
    (repo / "Makefile").write_text("help: ## Show this help\n\t@true\n", encoding="utf-8")
    return repo


def test_the_command_exits_clean_on_an_intact_chain(plane, capsys):
    code = cli.main(["ledger", "--repo", str(plane), "--ledger", str(FIXTURE)])
    printed = capsys.readouterr().out
    assert code == 0
    assert "Chain intact" in printed
    assert "alex@example.com" in printed


def test_the_command_exits_2_when_a_chain_is_broken(plane, tmp_path, capsys):
    records = lines_of(FIXTURE)
    records[4]["backup_id"] = "db-snapshot-FAKE"
    path = tmp_path / "staging.audit.jsonl"
    rewrite(path, records)

    code = cli.main(["ledger", "--repo", str(plane), "--ledger", str(path)])
    assert code == 2
    assert "Chain broken" in capsys.readouterr().out


def test_the_command_reads_one_deploy_in_full(plane, capsys):
    code = cli.main(["ledger", "last", "--repo", str(plane), "--ledger", str(FIXTURE)])
    printed = capsys.readouterr().out
    assert code == 0
    for question in ("Who deployed it?", "Who approved it?", "Can these records be trusted?"):
        assert question in printed
    assert "sam@example.com" in printed


# --- how long it took ---


BASE = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def at(minute: int) -> str:
    """Minutes from a fixed moment, so a test may run past the end of an hour."""
    return (BASE + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


def a_timed_deploy(release: str = "r1", start: int = 0, cutover: int = 10, live: int = 20):
    """One deploy whose records are minutes apart, so a span is a real figure."""
    records = a_full_deploy(release)
    minutes = {
        "deploy.started": start,
        "approval.verified": start + 1,
        "build.succeeded": start + 5,
        "cutover.started": cutover,
        "cutover.succeeded": live,
        "deploy.finished": live + 2,
    }
    for record in records:
        record["recorded_at"] = at(minutes[record["event"]])
        if record["event"] in ("cutover.started", "cutover.succeeded"):
            record["maintenance_window"] = True
    records.insert(4, event("maintenance.enabled", release))
    records[4]["recorded_at"] = at(cutover + 2)
    return records


def test_a_span_is_the_gap_between_the_two_records_that_bound_it(tmp_path):
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", a_timed_deploy()))
    [deployment] = ledger.deployments(chain)

    assert deployment.span("maintenance") == 8 * 60
    assert deployment.span("cutover") == 10 * 60
    assert deployment.span("build") == 5 * 60
    assert deployment.span("total") == 22 * 60


def test_a_span_with_a_record_missing_at_either_end_is_not_measured(tmp_path):
    records = [r for r in a_timed_deploy() if r["event"] != "deploy.finished"]
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    [deployment] = ledger.deployments(chain)

    assert deployment.span("total") is None
    assert "total" not in deployment.spans
    assert deployment.span("maintenance") == 8 * 60


def test_a_span_measured_as_zero_is_not_the_same_as_one_not_measured():
    """Zero seconds is a fast step; nothing at all is a step nobody can time."""
    assert ledger.spoken(0.0) == "under a second"
    assert ledger.spoken(None) == ""
    assert ledger.spoken(95) == "1m 35s"


def test_the_maintenance_answer_carries_how_long_the_page_was_up(tmp_path):
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", a_timed_deploy()))
    [deployment] = ledger.deployments(chain)
    said = answer(deployment, chain, "Did the site go into maintenance?")

    assert said.answer == "Yes, for 8m 00s"
    assert "8m 00s" in said.detail


def test_a_ledger_reports_the_typical_span_and_its_spread(tmp_path):
    records = (
        a_timed_deploy("r1", start=0, cutover=10, live=20)
        + a_timed_deploy("r2", start=30, cutover=40, live=44)
        + a_timed_deploy("r3", start=60, cutover=70, live=82)
    )
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    found = {t.key: t for t in ledger.timings(ledger.deployments(chain))}

    window = found["maintenance"]
    assert window.samples == 3
    # 8, 2 and 10 minutes: the middle one, not the mean.
    assert (window.typical, window.fastest, window.slowest) == (8 * 60, 2 * 60, 10 * 60)
    assert window.measured is True


def test_an_even_number_of_samples_takes_the_middle_pair(tmp_path):
    records = a_timed_deploy("r1", start=0, cutover=10, live=20) + a_timed_deploy(
        "r2", start=30, cutover=40, live=44
    )
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    found = {t.key: t for t in ledger.timings(ledger.deployments(chain))}
    assert found["maintenance"].typical == 5 * 60


def test_a_span_nothing_has_reached_says_so_rather_than_reporting_zero(tmp_path):
    """The quiet direction: a measure with no sample must never read as instant."""
    records = [r for r in a_full_deploy() if r["event"] != "cutover.succeeded"]
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    found = {t.key: t for t in ledger.timings(ledger.deployments(chain))}

    window = found["maintenance"]
    assert window.measured is False
    assert window.typical == 0.0
    assert "needed a maintenance window" in window.blocked
    assert found["to_verify"].blocked == ledger.NOTHING_TIMED["to_verify"]
    assert found["cutover"].blocked == ledger.NOT_REACHED


def test_a_record_whose_time_carries_no_zone_is_read_rather_than_thrown(tmp_path):
    """The writer stamps UTC, and a file that does not is still a file.

    Comparing an aware time with a naive one raises, and that comparison sits in
    the middle of measuring a span, so a single stamp without an offset took all
    three front ends down and exited as though nothing had been read. A file
    consistent with itself still measures correctly, because a span is a gap.
    """
    records = a_full_deploy("r1")
    records[3] = {**records[3], "recorded_at": "2026-09-01T10:04:00"}
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))

    assert chain.state == ledger.INTACT
    assert ledger.deployments(chain)[0].spans, "a readable deploy reported no timings at all"


def test_records_after_a_break_are_left_out_of_the_timings(tmp_path):
    """A figure is only as good as the records under it, so an edited one counts for nothing."""
    path = write_chain(
        tmp_path / "staging.audit.jsonl",
        a_timed_deploy("r1", start=0, cutover=10, live=20)
        + a_timed_deploy("r2", start=30, cutover=40, live=44),
    )
    records = lines_of(path)
    was = records[8]["recorded_at"]
    records[8]["recorded_at"] = at(35)
    assert records[8]["recorded_at"] != was, "the edit has to change something to be an edit"
    rewrite(path, records)

    chain = ledger.read(path)
    found = {t.key: t for t in ledger.timings(ledger.deployments(chain))}
    assert found["maintenance"].samples == 1
    assert found["maintenance"].typical == 8 * 60


def test_a_finish_with_no_outcome_is_a_finish(tmp_path):
    """The playbook's own test fixture writes one, and reading it as *no finish*
    called a deploy unfinished while its last record sat there saying otherwise."""
    records = a_full_deploy()
    records[-1].pop("outcome")
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    [deployment] = ledger.deployments(chain)

    assert deployment.outcome == ledger.FINISHED
    said = answer(deployment, chain, "Did it work?")
    assert said.answer == "Finished"
    assert "does not say how" in said.detail
    assert said.level == language.ATTENTION


def test_a_finish_that_says_it_did_not_work_is_a_problem(tmp_path):
    records = a_full_deploy()
    records[-1]["outcome"] = "failed"
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    [deployment] = ledger.deployments(chain)

    assert deployment.outcome == ledger.FAILED
    said = answer(deployment, chain, "Did it work?")
    assert (said.answer, said.level) == ("Did not succeed", language.PROBLEM)


def test_a_deploy_with_no_finish_record_at_all_still_reads_as_unfinished(tmp_path):
    """The quiet direction: the fix must not turn a missing finish into a finish."""
    records = [r for r in a_full_deploy() if r["event"] != "deploy.finished"]
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    assert ledger.deployments(chain)[0].outcome == ledger.UNFINISHED


def test_records_with_no_deploy_behind_them_are_one_group_that_says_so(tmp_path):
    """The playbook's warm-up suite leaves four, and four rows read as four deploys."""
    records = [event("warmup.completed", "r9", requested=4, ok=3, percent=75.0) for _ in range(4)]
    chain = ledger.read(write_chain(tmp_path / "test.audit.jsonl", records))
    [group] = ledger.deployments(chain)

    assert group.outcome == ledger.RECORDS_ONLY
    assert len(group.entries) == 4
    assert language.ledger_outcome(group.outcome).name == "Records only"


def test_a_deploy_after_loose_records_is_still_its_own_deploy(tmp_path):
    """The quiet direction: folding orphans must not swallow the deploy after them."""
    records = [event("warmup.completed", "r9", requested=1, ok=1), *a_full_deploy("r1")]
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    newest, older = ledger.deployments(chain)

    assert (newest.release, newest.outcome) == ("r1", ledger.SUCCEEDED)
    assert older.outcome == ledger.RECORDS_ONLY
    assert len(newest.entries) == 6


# --- the writer, where there is one to ask ---


def test_the_writer_still_hashes_a_record_the_way_this_reader_does(tmp_path):
    """The fixture is frozen. This asks the writer as it is today.

    `tests/fixtures/ledger/README.md` says why: a change to the playbook's
    canonicalisation makes every production ledger read as broken while the
    captured fixture keeps passing, because it was written under the old rule.

    Skipped where the playbook is not checked out, which is everywhere except a
    machine that has both.
    """
    where = os.environ.get("ORDANE_PLAYBOOK")
    if not where:
        pytest.skip("set ORDANE_PLAYBOOK to a playbook checkout to check against the writer")
    tool = Path(where) / "bin" / "audit-log"
    if not tool.exists():
        pytest.fail(f"ORDANE_PLAYBOOK is set and {tool} is not there")

    # It has no `.py`, so it is loaded by path. Its entry point is guarded, so
    # importing it runs nothing.
    loader = importlib.machinery.SourceFileLoader("audit_log_writer", str(tool))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    writer = importlib.util.module_from_spec(spec)
    loader.exec_module(writer)

    record = lines_of(FIXTURE)[0]
    assert writer.record_hash(record) == ledger.record_hash(record), (
        "the writer and this reader no longer agree on what a record hashes to"
    )


# --- an excerpt of a ledger, which is what an evidence bundle is ---


def a_bundle(tmp_path, keep, folder="evidence"):
    """An evidence bundle as `audit-log write-evidence` writes one.

    `keep` is the indices of the records to copy, because the writer selects by
    release rather than slicing: anything deployed in between is left behind and
    the numbering skips it.
    """
    whole = write_chain(tmp_path / "whole.audit.jsonl", a_full_deploy("r1"))
    lines = whole.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    selected = [records[i] for i in keep]

    out = tmp_path / folder
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in selected),
        encoding="utf-8",
    )
    rows = "\n".join(
        f"{r['seq']}  {r['prev_hash']}  {r['hash']}  {r.get('event', '')}" for r in selected
    )
    (out / "chain.txt").write_text(
        f"log: {whole}\n"
        f"records in log: {len(records)}\n"
        f"head hash: {records[-1]['hash']}\n"
        "chain verified: yes\n"
        "\n"
        "seq  prev_hash  hash  event\n" + rows + "\n",
        encoding="utf-8",
    )
    (out / "summary.md").write_text("# r1\n", encoding="utf-8")
    (out / "SHA256SUMS").write_text("", encoding="utf-8")
    return out / "audit.jsonl"


def test_an_evidence_bundle_is_read_as_an_excerpt(plane, tmp_path):
    """A bundle is a copy somebody asked for, and was reported as broken at line 1."""
    chain = ledger.read(a_bundle(tmp_path, range(2, 6)))

    assert chain.state == ledger.FRAGMENT
    assert chain.broken_line == 0, "a bundle was reported as breaking somewhere"
    assert chain.entries, "the bundle's records were dropped"


def test_a_bundle_whose_records_skip_what_ran_in_between(plane, tmp_path):
    """The shape the writer really produces: it selects one release, so `seq` has gaps.

    Reading a bundle as a chain cannot work, whatever the arithmetic: the record
    after a gap links to one the bundle does not hold.
    """
    cut = a_bundle(tmp_path, [0, 1, 2, 5])
    seqs = [json.loads(line)["seq"] for line in cut.read_text(encoding="utf-8").splitlines()]
    assert seqs != list(range(seqs[0], seqs[0] + len(seqs))), "this fixture has no gap in it"

    chain = ledger.read(cut)

    assert chain.state == ledger.FRAGMENT
    assert all(e.trusted for e in chain.entries)


def test_a_bundle_says_which_log_it_came_from(plane, tmp_path):
    """The bundle's own numbers are what an auditor checks it against."""
    chain = ledger.read(a_bundle(tmp_path, range(2, 6)))

    assert chain.bundle is not None
    assert chain.bundle.log.endswith("whole.audit.jsonl")
    assert chain.bundle.records == 6
    assert chain.bundle.head


def test_a_record_edited_inside_a_bundle_still_breaks_it(plane, tmp_path):
    """The point is not to trust a bundle, it is to stop calling a good one a fake."""
    cut = a_bundle(tmp_path, range(2, 6))
    lines = cut.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["release"] = "something-else"
    lines[1] = json.dumps(record, sort_keys=True)
    cut.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert ledger.read(cut).state == ledger.BROKEN


def test_a_record_swapped_for_one_the_bundle_never_listed_breaks_it(plane, tmp_path):
    """A record that hashes correctly is still not this bundle's record."""
    cut = a_bundle(tmp_path, range(2, 6))
    other = a_bundle(tmp_path, range(0, 6), folder="second")
    lines = cut.read_text(encoding="utf-8").splitlines()
    lines[1] = other.read_text(encoding="utf-8").splitlines()[0]
    cut.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert ledger.read(cut).state == ledger.BROKEN


def test_a_ledger_with_its_opening_records_gone_is_broken(plane, tmp_path):
    """The direction that matters: cutting records off the front is a tamper, not an excerpt.

    Without the file the writer puts beside a bundle, there is nothing saying
    these records were ever asked for, and the file's own first record cannot be
    the thing that decides it.
    """
    whole = write_chain(tmp_path / "staging.audit.jsonl", a_full_deploy("r1"))
    lines = whole.read_text(encoding="utf-8").splitlines()
    whole.write_text("\n".join(lines[3:]) + "\n", encoding="utf-8")

    chain = ledger.read(whole)

    assert chain.state == ledger.BROKEN
    assert chain.broken_line == 1
    assert not any(e.trusted for e in chain.entries)


def test_an_excerpt_says_it_cannot_be_trusted_on_its_own(plane, tmp_path):
    chain = ledger.read(a_bundle(tmp_path, range(2, 6)))
    deployments = ledger.deployments(chain)
    answers = ledger.answers(deployments[0], chain)
    trust = next(a for a in answers if a.question == "Can these records be trusted?")

    assert trust.answer == "Not on their own"
    assert trust.level == language.ATTENTION
    assert "whole.audit.jsonl" in trust.detail, "the answer does not say what to check it against"


def test_a_whole_ledger_is_still_intact(plane, tmp_path):
    """The quiet direction: the change must not turn every ledger into an excerpt."""
    whole = write_chain(tmp_path / "staging.audit.jsonl", a_full_deploy("r1"))
    assert ledger.read(whole).state == ledger.INTACT


# --- a release deployed twice ---


def test_a_retried_release_leaves_two_attempts_and_both_can_be_reached(plane, tmp_path):
    """Asking for the name alone reached the newer one for ever, and nothing said so."""
    records = [*a_full_deploy("r1"), *a_full_deploy("r1")]
    path = write_chain(tmp_path / "staging.audit.jsonl", records)
    books = ledger.gather(plane, [], [path])
    older, newer = sorted(books[0].deployments, key=lambda d: d.started_at)

    assert older.ref != newer.ref, "two attempts at one release share a reference"
    assert ledger.find(books, "r1")[1].ref == newer.ref, "the bare name reaches the wrong one"
    assert ledger.find(books, older.ref)[1].ref == older.ref, "the earlier attempt is unreachable"
    assert [d.ref for _, d in ledger.attempts(books, "r1")] == [older.ref, newer.ref]


def test_a_deploy_with_no_release_still_has_a_reference(plane, tmp_path):
    """Records belonging to no deploy are a group, and a group with no name is not addressable."""
    records = [event("warmup.completed", "", requested=1, ok=1)]
    path = write_chain(tmp_path / "staging.audit.jsonl", records)
    books = ledger.gather(plane, [], [path])
    group = books[0].deployments[0]

    assert group.release == ""
    assert group.ref, "a group with no release has nothing to address it by"
    assert ledger.find(books, group.ref)[1].ref == group.ref


# --- what the command says to whatever runs it ---


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("missing", 1),
        ("no-config", 1),
        ("empty-glob", 1),
        ("empty-file", 0),
        ("intact", 0),
        ("intact-and-missing", 0),
        ("intact-and-unreadable", 1),
    ],
)
def test_the_exit_status_says_whether_anything_was_read(plane, tmp_path, case, expected):
    """A scheduled job has to hear about a ledger it could not read, not only one that was edited.

    Two quiet directions, and they are not the same. A ledger that exists and
    holds no deploys yet is a fresh environment, not a fault. A path with no
    file at it is the same shape as that fresh environment, so it cannot fail
    the job either. A file that is there and will not open is a fault whatever
    else read cleanly, which is the case that used to pass.
    """
    argv = ["ledger", "--repo", str(plane)]
    if case == "missing":
        argv += ["--ledger", str(tmp_path / "nowhere.audit.jsonl")]
    elif case == "empty-glob":
        (plane / config_module.CONFIG_NAME).write_text(
            "ledgers: [state/*.audit.jsonl]\n", encoding="utf-8"
        )
    elif case == "empty-file":
        empty = tmp_path / "staging.audit.jsonl"
        empty.write_text("", encoding="utf-8")
        argv += ["--ledger", str(empty)]
    elif case == "intact":
        argv += ["--ledger", str(FIXTURE)]
    elif case == "intact-and-missing":
        argv += ["--ledger", str(FIXTURE), "--ledger", str(tmp_path / "nowhere.audit.jsonl")]
    elif case == "intact-and-unreadable":
        garbled = tmp_path / "production.audit.jsonl"
        garbled.write_bytes(b"\xff\xfe not text at all\n")
        argv += ["--ledger", str(FIXTURE), "--ledger", str(garbled)]
    assert cli.main(argv) == expected


def test_a_broken_chain_outranks_everything_else_read(plane, tmp_path, capsys):
    records = lines_of(FIXTURE)
    records[4]["backup_id"] = "db-snapshot-FAKE"
    broken = tmp_path / "staging.audit.jsonl"
    rewrite(broken, records)

    code = cli.main(
        ["ledger", "--repo", str(plane), "--ledger", str(FIXTURE), "--ledger", str(broken)]
    )
    assert code == 2
    assert "Chain broken" in capsys.readouterr().out


# --- a format newer than this reader ---


def test_a_newer_schema_is_named_rather_than_swallowed(tmp_path):
    """The writer's contract says schema moves when fields stop being only added."""
    records = a_full_deploy()
    for record in records:
        record["schema"] = ledger.SCHEMA + 1
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))

    assert chain.state == ledger.INTACT, "a newer format is still a readable chain"
    assert chain.newer_schema == ledger.SCHEMA + 1
    assert "newer than this reader knows" in language.newer_format(chain.newer_schema)


def test_the_schema_this_reader_was_written_against_is_not_flagged(tmp_path):
    """The quiet direction: today's records must not all read as a newer format."""
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", a_full_deploy()))
    assert chain.newer_schema == 0
    assert ledger.read(FIXTURE).newer_schema == 0


def test_a_deploy_with_no_build_or_cutover_span_reads_as_one_sentence(tmp_path):
    """`Took 5m 00s. .` is what an empty list did to the sentence after it."""
    records = [
        event("deploy.started", branch="main", goes_live=True),
        event("deploy.finished", outcome="success"),
    ]
    chain = ledger.read(write_chain(tmp_path / "staging.audit.jsonl", records))
    [deployment] = ledger.deployments(chain)
    said = answer(deployment, chain, "When?")
    assert ". ." not in said.detail
    assert said.detail.endswith(".")
