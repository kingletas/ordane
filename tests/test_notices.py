"""What a run told the outside world, read back out of its own output.

Every notification in this estate's deploy is `failed_when: false`, a silently
skipped webhook is the failure mode the playbook's own comment names. It says
which landed; this reads it.
"""

from ordane.record import notices

TASK = "Report which notifications landed"

# Verbatim from `ansible-playbook`, not remembered.
REAL = """
PLAY [Probe] *******************************************************************

TASK [Report which notifications landed] ***************************************
ok: [localhost] => {
    "msg": {
        "newrelic": "0 of 3 apps FAILED",
        "noibu": "FAILED - status 502",
        "pagerduty": "ok"
    }
}

PLAY RECAP *********************************************************************
localhost                  : ok=1    changed=0    unreachable=0    failed=0
"""


def test_a_run_says_which_notifications_landed():
    told = notices.read(REAL, TASK)
    assert told.any
    assert told.summary == "2 of 3 landed"
    assert {one.name: one.state for one in told.notices} == {
        "pagerduty": "landed",
        "newrelic": "landed",
        "noibu": "missed",
    }


def test_none_failed_is_not_a_failure():
    """`0 of 3 apps FAILED` is the healthiest answer there is, and it says FAILED."""
    assert notices.Notice("newrelic", "0 of 3 apps FAILED").state == "landed"
    assert notices.Notice("newrelic", "0 of 12 apps FAILED").state == "landed"
    assert notices.Notice("newrelic", "1 of 3 apps FAILED").state == "missed"
    assert notices.Notice("newrelic", "2 of 3 apps FAILED").state == "missed"


def test_only_the_missed_ones_are_the_ones_worth_acting_on():
    assert [one.name for one in notices.read(REAL, TASK).missed] == ["noibu"]


def test_something_neither_ok_nor_failed_is_not_given_a_verdict():
    assert notices.Notice("thing", "window opened until 14:00").state == "unclear"
    assert notices.Notice("thing", "ok").state == "landed"
    assert notices.Notice("thing", "OK").state == "landed"


def test_a_task_the_configuration_does_not_name_is_not_read():
    assert not notices.read(REAL, "").any
    assert not notices.read(REAL, "Some other task").any


def test_output_holding_no_such_task_says_nothing():
    assert not notices.read("PLAY RECAP ***\nweb1 : ok=1\n", TASK).any
    assert not notices.read("", TASK).any


def test_a_task_that_printed_something_that_is_not_a_mapping_is_skipped():
    text = f'TASK [{TASK}] ***\nok: [localhost] => {{\n    "msg": "just a sentence"\n}}\n'
    assert not notices.read(text, TASK).any


def test_the_next_task_ends_the_search_rather_than_running_into_it():
    text = (
        f"TASK [{TASK}] ***\n"
        "skipping: [localhost]\n"
        'TASK [Something else] ***\nok: [localhost] => {\n    "msg": {"a": "ok"}\n}\n'
    )
    assert not notices.read(text, TASK).any


def test_colour_does_not_stop_it_being_read():
    coloured = REAL.replace("TASK [", "\x1b[0;33mTASK [").replace("ok: [", "\x1b[0;32mok: [")
    assert notices.read(coloured, TASK).summary == "2 of 3 landed"
