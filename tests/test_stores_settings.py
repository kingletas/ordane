"""Writing the shared-store settings, which is the one file this console writes.

It holds a token, so the mode it is created with is the point of the exercise:
a common umask gives a hand-written file 0664, and refusing to write it never
kept the token off the disk.
"""

from __future__ import annotations

import os
import stat

import pytest

from ordane.insight import stores

# Spelled from `stat` rather than as octal literals: these are deliberately
# loose modes, set so the code can be seen tightening them, and a bare 0o664 in
# a test reads exactly like one in production.
OWNER_ONLY = stat.S_IRWXU
GROUP_WRITABLE = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP
GROUP_READABLE = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP
WORLD_READABLE = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
NO_WRITING = stat.S_IRUSR | stat.S_IXUSR

TOKEN_KEY = f"{stores.PREFIX}INFLUX_TOKEN"
URL_KEY = f"{stores.PREFIX}INFLUX_URL"


def test_it_writes_what_it_was_given(tmp_path):
    path = tmp_path / "stores.env"
    stores.write_settings_file({URL_KEY: "http://influx.example", TOKEN_KEY: "t0ken"}, path)
    read = stores.read_settings_file(path)
    assert read[URL_KEY] == "http://influx.example"
    assert read[TOKEN_KEY] == "t0ken"


def test_the_file_is_owner_only(tmp_path):
    """The whole reason this is written rather than left to a text editor."""
    path = tmp_path / "stores.env"
    stores.write_settings_file({TOKEN_KEY: "t0ken"}, path)
    assert stat.S_IMODE(path.stat().st_mode) == stores.PRIVATE_MODE


def test_an_existing_open_file_is_tightened(tmp_path):
    path = tmp_path / "stores.env"
    path.write_text("old\n", encoding="utf-8")
    os.chmod(path, GROUP_WRITABLE)
    stores.write_settings_file({TOKEN_KEY: "t0ken"}, path)
    assert stat.S_IMODE(path.stat().st_mode) == stores.PRIVATE_MODE


def test_it_survives_a_permissive_umask(tmp_path):
    """O_CREAT respects the umask, so the mode is set explicitly as well."""
    path = tmp_path / "stores.env"
    previous = os.umask(0o000)
    try:
        stores.write_settings_file({TOKEN_KEY: "t0ken"}, path)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(path.stat().st_mode) == stores.PRIVATE_MODE


def test_an_empty_value_is_left_out(tmp_path):
    """An empty line would shadow the default the reader falls back to."""
    path = tmp_path / "stores.env"
    stores.write_settings_file({URL_KEY: "http://influx.example", TOKEN_KEY: "  "}, path)
    assert TOKEN_KEY not in stores.read_settings_file(path)


def test_a_key_this_file_does_not_hold_is_refused(tmp_path):
    with pytest.raises(stores.SettingsError):
        stores.write_settings_file({"PATH": "anything"}, tmp_path / "stores.env")


def test_writing_replaces_rather_than_appends(tmp_path):
    path = tmp_path / "stores.env"
    stores.write_settings_file({URL_KEY: "http://first.example"}, path)
    stores.write_settings_file({URL_KEY: "http://second.example"}, path)
    assert stores.read_settings_file(path)[URL_KEY] == "http://second.example"
    assert "first" not in path.read_text(encoding="utf-8")


def test_a_directory_that_cannot_be_written_is_reported(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    os.chmod(blocked, NO_WRITING)
    try:
        with pytest.raises(stores.SettingsError):
            stores.write_settings_file({URL_KEY: "http://x"}, blocked / "stores.env")
    finally:
        os.chmod(blocked, OWNER_ONLY)


# --- and the check that says an existing file is readable by other people ---


def test_a_tight_file_says_nothing(tmp_path):
    path = tmp_path / "stores.env"
    stores.write_settings_file({TOKEN_KEY: "t0ken"}, path)
    assert stores.too_open(path) == ""


def test_a_world_readable_file_is_named(tmp_path):
    path = tmp_path / "stores.env"
    path.write_text("x\n", encoding="utf-8")
    os.chmod(path, WORLD_READABLE)
    assert "every account on this machine" in stores.too_open(path)


def test_a_group_readable_file_is_named(tmp_path):
    path = tmp_path / "stores.env"
    path.write_text("x\n", encoding="utf-8")
    os.chmod(path, GROUP_READABLE)
    assert "everyone in the group" in stores.too_open(path)


def test_a_file_that_is_not_there_says_nothing(tmp_path):
    assert stores.too_open(tmp_path / "absent.env") == ""
