from ordane.record import summary
from ordane.record.summary import parse

RECAP = """\
PLAY [Deploy the release] ******************************************************

TASK [Gathering Facts] *********************************************************
ok: [web1]
ok: [builder]

TASK [Unarchive the current release] *******************************************
changed: [web1]
fatal: [web2]: FAILED! => {"changed": false, "msg": "tar exited with status 2"}

TASK [Flip the symlink] ********************************************************
ok: [web1]

PLAY RECAP *********************************************************************
builder                    : ok=61   changed=19   unreachable=0    failed=0    skipped=8    rescued=0    ignored=0
web1                       : ok=47   changed=12   unreachable=0    failed=0    skipped=11   rescued=0    ignored=0
web2                       : ok=3    changed=0    unreachable=0    failed=1    skipped=0    rescued=0    ignored=0
varnish                    : ok=0    changed=0    unreachable=1    failed=0    skipped=0    rescued=0    ignored=0
"""


def test_every_recap_row_becomes_a_host():
    summary = parse(RECAP)
    assert summary.has_recap
    assert [h.host for h in summary.hosts] == ["builder", "web1", "web2", "varnish"]


def test_the_counts_are_read_from_the_recap():
    summary = parse(RECAP)
    assert summary.ok == 111
    assert summary.changed == 31
    assert summary.failed == 2


def test_a_host_that_failed_or_was_unreachable_is_marked_bad():
    hosts = {h.host: h for h in parse(RECAP).hosts}
    assert hosts["web2"].bad
    assert hosts["varnish"].bad
    assert not hosts["web1"].bad
    assert hosts["web1"].state == "changed"


def test_an_unreachable_host_is_named():
    assert parse(RECAP).unreachable_hosts == ["varnish"]


def test_a_failure_carries_the_task_that_produced_it():
    failures = parse(RECAP).failures
    assert len(failures) == 1
    assert failures[0].host == "web2"
    assert failures[0].task == "Unarchive the current release"
    assert "tar exited with status 2" in failures[0].message


def test_tasks_and_plays_are_counted():
    summary = parse(RECAP)
    assert summary.tasks == 3
    assert summary.plays == 1


def test_the_headline_reads_without_opening_the_log():
    assert parse(RECAP).headline == "4 hosts, 31 changed, 2 failed"


def test_output_with_no_recap_says_it_has_none_rather_than_reporting_zeros():
    summary = parse("make: *** [Makefile:12: deploy] Error 2\n")
    assert not summary.has_recap
    assert summary.headline == ""
    assert summary.hosts == []


def test_colour_codes_do_not_defeat_the_parser():
    coloured = "\x1b[0;32mPLAY RECAP\x1b[0m ****\n\x1b[0;32mweb1  : ok=1    changed=0    unreachable=0    failed=0\x1b[0m\n"
    summary = parse(coloured)
    assert summary.has_recap
    assert summary.hosts[0].host == "web1"


def test_a_run_of_failures_is_capped_and_the_remainder_counted():
    lines = ["TASK [Loop] ***"]
    lines += [f'fatal: [host{i}]: FAILED! => {{"msg": "no"}}' for i in range(40)]
    summary = parse("\n".join(lines))
    assert len(summary.failures) == 25
    assert summary.truncated_failures == 15


def test_a_summary_round_trips_through_its_record():
    from ordane.record.summary import Summary

    original = parse(RECAP)
    restored = Summary.from_record(original.as_record())
    assert restored.headline == original.headline
    assert [h.host for h in restored.hosts] == [h.host for h in original.hosts]
    assert restored.failures[0].task == original.failures[0].task


# --- where a run has got to, which nothing could say while it was alive ---


def test_the_task_a_run_is_on_is_read_from_what_it_has_printed():
    where = summary.progress(
        "PLAY [Start the build process] ***\n"
        "TASK [Gathering Facts] ***\n"
        "ok: [web1]\n"
        "PLAY [Building the release] ***\n"
        "TASK [Run composer install] ***\n"
    )
    assert where.play == "Building the release"
    assert where.task == "Run composer install"
    assert (where.plays, where.tasks) == (2, 2)
    assert "Run composer install" in where.summary


def test_a_run_that_has_printed_nothing_yet_says_nothing():
    assert not summary.progress("").known
    assert summary.progress("").summary == ""


def test_the_first_task_is_not_reported_as_one_task_in():
    assert "first task" in summary.progress("TASK [Gathering Facts] ***\n").summary


def test_a_handler_counts_as_a_task_because_ansible_prints_it_as_one():
    assert summary.progress("HANDLER [Restart php-fpm] ***\n").task == "Restart php-fpm"


# --- what `ansible` answers, which is not a recap ---


def test_a_question_asked_of_a_group_is_read_host_by_host():
    read = summary.from_asked(
        "[WARNING]: an interpreter warning\n"
        'example-docker | SUCCESS => {\n    "ping": "pong"\n}\n'
        'web2 | UNREACHABLE! => {\n    "msg": "No route to host"\n}\n'
        'web3 | FAILED! => {"msg": "boom"}\n'
        'web4 | CHANGED => {"changed": true}\n'
    )
    assert read.has_recap
    assert [h.host for h in read.hosts] == ["example-docker", "web2", "web3", "web4"]
    assert read.ok == 2
    assert read.changed == 1
    assert read.failed == 2
    assert {f.kind for f in read.failures} == {"unreachable", "failed"}


def test_a_host_that_answers_twice_is_counted_once():
    read = summary.from_asked("web1 | SUCCESS => {}\nweb1 | SUCCESS => {}\n")
    assert len(read.hosts) == 1


def test_output_with_no_answers_in_it_has_no_recap():
    assert not summary.from_asked("ansible: command not found\n").has_recap
    assert not summary.from_asked("").has_recap


def test_a_playbook_recap_is_not_read_this_way():
    """The two formats must not be confused: a playbook prints PLAY RECAP."""
    assert not summary.from_asked(
        "PLAY RECAP ****\nweb1 : ok=3 changed=1 unreachable=0 failed=0\n"
    ).has_recap
