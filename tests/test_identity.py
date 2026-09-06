import os

from ordane.core import identity


def test_the_user_comes_from_the_process_rather_than_the_environment(monkeypatch):
    """`$USER` is a string anybody can set, and under sudo it lies."""
    monkeypatch.setenv("USER", "somebody-else")
    assert identity.who().user != "somebody-else" or os.geteuid() != os.getuid()


def test_an_ordinary_account_is_not_root():
    actor = identity.who()
    assert actor.is_root == (actor.uid == 0)


def test_the_name_carries_the_machine_because_a_shared_history_needs_it():
    actor = identity.who()
    assert actor.host in actor.name


def test_root_says_so_in_its_summary():
    actor = identity.Actor(user="root", uid=0, host="box")
    assert actor.summary == "root@box"


def test_a_uid_zero_account_by_another_name_is_still_flagged():
    actor = identity.Actor(user="toor", uid=0, host="box")
    assert "uid 0" in actor.summary


def test_root_by_sudo_names_who_escalated():
    actor = identity.Actor(user="root", uid=0, host="box", escalated_from="ada")
    assert actor.summary == "root@box, via sudo from ada"


def test_an_ordinary_summary_is_just_the_name():
    actor = identity.Actor(user="ada", uid=1000, host="box")
    assert actor.summary == "ada@box"


def test_a_uid_with_no_account_still_produces_an_actor(monkeypatch):
    monkeypatch.setattr(identity.os, "geteuid", lambda: 999999)
    assert identity.who().user == "999999"


def test_sudo_is_only_read_when_it_is_actually_root(monkeypatch):
    monkeypatch.setenv("SUDO_USER", "someone")
    monkeypatch.setattr(identity.os, "geteuid", lambda: 1000)
    assert identity.who().escalated_from == ""


def test_the_root_warning_says_what_it_costs_rather_than_only_that_it_is_bad():
    assert "run history" in identity.ROOT_WARNING
    assert "does not need it here" in identity.ROOT_WARNING
