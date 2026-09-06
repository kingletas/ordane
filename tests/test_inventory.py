"""What is inside an environment, which the console could not see at all.

The shape here is the one a Magento control plane actually has: a `builder`
that packages the release, an `apps` group it is shipped to, and a `web` group
that is those plus admin and cron. Knowing which host builds is the difference
between `deploy to production` and knowing what that means.
"""

import json

from ordane.core import inventory

# `ansible-inventory --list` against a real environment, trimmed to shape.
REAL = json.dumps(
    {
        "_meta": {"hostvars": {"stage-builder": {"ansible_user": "ubuntu"}}},
        "all": {
            "children": ["admin", "apps", "builder", "cron", "varnish", "ungrouped"],
        },
        "admin": {"hosts": ["stage-admin"]},
        "apps": {"hosts": ["stage-web1", "stage-web2", "stage-web3"]},
        "builder": {"hosts": ["stage-builder"]},
        "cron": {"hosts": ["stage-cron"]},
        "varnish": {"hosts": ["stage-varnish"]},
        "ungrouped": {},
        "web": {"children": ["admin", "apps", "cron"]},
    }
)


def test_the_builder_is_a_group_like_any_other_and_can_be_named():
    read = inventory.parse(REAL)
    assert read.known
    builder = read.group("builder")
    assert builder is not None
    assert builder.one_host == "stage-builder"


def test_a_group_of_groups_carries_its_children_hosts():
    web = inventory.parse(REAL).group("web")
    assert web is not None
    assert set(web.hosts) == {"stage-admin", "stage-web1", "stage-web2", "stage-web3", "stage-cron"}


def test_the_bookkeeping_groups_are_not_roles():
    names = {group.name for group in inventory.parse(REAL).groups}
    assert "all" not in names
    assert "ungrouped" not in names


def test_every_host_is_counted_once_however_many_groups_hold_it():
    read = inventory.parse(REAL)
    assert len(read.hosts) == 7
    assert len(set(read.hosts)) == len(read.hosts)


def test_a_group_written_as_a_plain_list_is_read_too():
    read = inventory.parse(json.dumps({"builder": ["one-host"]}))
    assert read.group("builder").hosts == ("one-host",)


def test_a_child_that_points_back_at_its_parent_does_not_loop():
    """A malformed inventory should be unhelpful, not a hang."""
    read = inventory.parse(
        json.dumps({"a": {"hosts": ["h1"], "children": ["b"]}, "b": {"children": ["a"]}})
    )
    assert read.group("a").hosts == ("h1",)


def test_an_empty_group_is_left_out_rather_than_shown_as_a_role():
    names = {group.name for group in inventory.parse(json.dumps({"web": {"hosts": []}})).groups}
    assert names == set()


def test_something_that_is_not_json_is_reported_rather_than_raised():
    assert inventory.parse("not json at all").error
    assert inventory.parse("[1, 2, 3]").error


def test_an_environment_with_no_inventory_says_so(tmp_path):
    assert "no inventory" in inventory.read(tmp_path, "").error


def test_a_missing_ansible_is_named_rather_than_blamed_on_the_repository(tmp_path, monkeypatch):
    def missing(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(inventory.subprocess, "run", missing)
    read = inventory.read(tmp_path, "inventory/staging")
    assert "ansible-inventory is not on the PATH" in read.error
    assert "Ansible" in read.hint


def test_ansible_refusing_reports_its_own_words(tmp_path, monkeypatch):
    class Refused:
        returncode = 1
        stdout = ""
        stderr = "ERROR! Unable to parse inventory/staging as an inventory source"

    monkeypatch.setattr(inventory.subprocess, "run", lambda *a, **k: Refused())
    read = inventory.read(tmp_path, "inventory/staging")
    assert not read.known
    assert "Unable to parse" in read.hint
