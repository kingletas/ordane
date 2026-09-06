"""Running a command on the machine rather than in the sandbox.

The sandboxed branch cannot be exercised by being in a sandbox, so the marker
file is pointed somewhere a test controls. That is the only honest way to test
it from outside one, and it means the branch is covered rather than hoped for.
"""

from __future__ import annotations

import subprocess

from ordane.core import host


def test_a_normal_install_spawns_directly():
    assert not host.sandboxed()
    assert host.argv(["make", "help"]) == ["make", "help"]


def test_inside_a_sandbox_the_command_goes_to_the_host(monkeypatch, tmp_path):
    marker = tmp_path / "flatpak-info"
    marker.write_text("[Application]\n", encoding="utf-8")
    monkeypatch.setattr(host, "SANDBOX_MARKER", marker)
    assert host.sandboxed()
    assert host.argv(["make", "help"]) == ["flatpak-spawn", "--host", "make", "help"]


def test_the_original_command_is_not_mutated(monkeypatch, tmp_path):
    """The caller keeps its argv: what is recorded must stay what was asked for."""
    marker = tmp_path / "flatpak-info"
    marker.write_text("[Application]\n", encoding="utf-8")
    monkeypatch.setattr(host, "SANDBOX_MARKER", marker)
    asked = ["ansible-playbook", "-i", "inventory/staging", "deploy.yml"]
    host.argv(asked)
    assert asked == ["ansible-playbook", "-i", "inventory/staging", "deploy.yml"]


def test_which_asks_this_machine_when_not_sandboxed():
    assert host.which("sh") is not None
    assert host.which("a-command-that-is-not-here-9987") is None


def test_which_asks_the_host_when_sandboxed(monkeypatch, tmp_path):
    marker = tmp_path / "flatpak-info"
    marker.write_text("[Application]\n", encoding="utf-8")
    monkeypatch.setattr(host, "SANDBOX_MARKER", marker)
    host.which.cache_clear()
    seen = {}

    def spawned(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="/usr/bin/make\n", stderr="")

    monkeypatch.setattr(host.shutil, "which", lambda _n: "/usr/bin/flatpak-spawn")
    monkeypatch.setattr(host.subprocess, "run", spawned)
    assert host.which("make") == "/usr/bin/make"
    assert seen["argv"][:2] == ["flatpak-spawn", "--host"]
    host.which.cache_clear()


def test_which_answers_nothing_when_the_host_cannot_be_asked(monkeypatch, tmp_path):
    """No flatpak-spawn means no answer, not a wrong one."""
    marker = tmp_path / "flatpak-info"
    marker.write_text("[Application]\n", encoding="utf-8")
    monkeypatch.setattr(host, "SANDBOX_MARKER", marker)
    monkeypatch.setattr(host.shutil, "which", lambda _n: None)
    host.which.cache_clear()
    assert host.which("make") is None
    host.which.cache_clear()


def test_a_spawn_that_raises_is_not_an_answer(monkeypatch, tmp_path):
    marker = tmp_path / "flatpak-info"
    marker.write_text("[Application]\n", encoding="utf-8")
    monkeypatch.setattr(host, "SANDBOX_MARKER", marker)
    monkeypatch.setattr(host.shutil, "which", lambda _n: "/usr/bin/flatpak-spawn")

    def refuses(*_a, **_k):
        raise OSError("no portal")

    monkeypatch.setattr(host.subprocess, "run", refuses)
    host.which.cache_clear()
    assert host.which("make") is None
    host.which.cache_clear()
