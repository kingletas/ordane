"""The host-by-task grid, read back out of what Ansible actually printed.

Ansible says what every host did to every task and then throws it away into a
recap of totals. These are the cases that decide whether the grid is a true
reading of the output or a picture that happens to look plausible.
"""

from ordane.record import lanes

OUTPUT = """
PLAY [staging] *********************

TASK [Gathering Facts] *************
ok: [web-01]
ok: [web-02]

TASK [Sync files] ******************
changed: [web-01]
skipping: [web-02]

TASK [Restart] *********************
changed: [web-01]
fatal: [web-02]: FAILED! => {"msg": "systemd said no"}

PLAY RECAP *************************
web-01 : ok=3 changed=2 unreachable=0 failed=0 skipped=0
web-02 : ok=1 changed=0 unreachable=0 failed=1 skipped=1
"""

LIVE = """
PLAY [staging] *********************

TASK [Gathering Facts] *************
ok: [web-01]
ok: [web-02]

TASK [Sync files] ******************
changed: [web-01]
"""


def test_the_grid_is_the_tasks_in_the_order_they_ran():
    grid = lanes.read(OUTPUT)
    assert grid.tasks == ["Gathering Facts", "Sync files", "Restart"]
    assert grid.hosts == ["web-01", "web-02"]


def test_each_cell_is_what_that_host_did_to_that_task():
    grid = lanes.read(OUTPUT)
    assert grid.state("web-01", "Sync files") == lanes.CHANGED
    assert grid.state("web-02", "Sync files") == lanes.SKIPPED
    assert grid.state("web-02", "Restart") == lanes.FAILED


def test_a_host_that_has_not_answered_the_current_task_is_running():
    grid = lanes.read(LIVE)
    assert grid.current == "Sync files"
    assert grid.state("web-02", "Sync files", live=True) == lanes.RUNNING
    assert grid.state("web-02", "Sync files", live=False) == lanes.PENDING


def test_the_recap_ends_the_run_so_nothing_is_left_looking_live():
    grid = lanes.read(OUTPUT)
    assert grid.current == ""
    assert grid.state("web-02", "Restart", live=True) == lanes.FAILED


def test_tasks_done_counts_only_the_ones_every_host_finished():
    assert lanes.read(LIVE).done == 1
    assert lanes.read(OUTPUT).done == 3


def test_a_loop_reporting_once_an_item_leaves_the_worst_result_in_the_cell():
    text = """
TASK [Copy each file] **************
ok: [web-01] => (item=a)
changed: [web-01] => (item=b)
ok: [web-01] => (item=c)
"""
    assert lanes.read(text).state("web-01", "Copy each file") == lanes.CHANGED


def test_a_delegated_result_is_still_the_host_it_names():
    text = "TASK [Notify] ***\nchanged: [web-01 -> localhost]\n"
    grid = lanes.read(text)
    assert grid.hosts == ["web-01"]


def test_two_tasks_with_one_name_are_two_columns():
    text = "TASK [Wait] ***\nok: [a]\n\nTASK [Wait] ***\nchanged: [a]\n"
    grid = lanes.read(text)
    assert grid.tasks == ["Wait", "Wait (2)"]
    assert grid.state("a", "Wait (2)") == lanes.CHANGED


def test_a_question_asked_of_a_group_is_one_column():
    text = "web-01 | SUCCESS => {}\nweb-02 | UNREACHABLE! => {}\n"
    grid = lanes.read(text)
    assert grid.tasks == ["answered"]
    assert grid.state("web-02", "answered") == lanes.FAILED


def test_a_run_that_printed_nothing_has_no_grid_rather_than_an_empty_one():
    assert not lanes.read("").known
    assert not lanes.read("PLAY RECAP ***\nweb-01 : ok=1 changed=0").known


def test_a_long_run_keeps_the_newest_tasks_and_says_how_many_it_dropped():
    text = "".join(f"TASK [step {index}] ***\nok: [a]\n" for index in range(lanes.MAX_TASKS + 5))
    grid = lanes.read(text)
    assert len(grid.tasks) == lanes.MAX_TASKS
    assert grid.hidden_tasks == 5
    assert grid.tasks[-1] == f"step {lanes.MAX_TASKS + 4}"


def test_colour_codes_do_not_stop_it_reading():
    text = "\x1b[0;32mTASK [Sync] ***\x1b[0m\n\x1b[0;33mchanged: [web-01]\x1b[0m\n"
    assert lanes.read(text).state("web-01", "Sync") == lanes.CHANGED
