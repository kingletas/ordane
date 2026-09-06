"""The run that stops and waits, which could not be run from here at all.

A playbook needing `--ask-vault-pass` sat on a prompt nothing could see and
nothing could answer. The runner already allocates a pty, which is exactly what
a prompt needs, so this is about noticing one without inventing one.
"""

from ordane.record import runner
from ordane.record.redact import Redactor
from ordane.record.store import Run, RunStore, new_id


def _a_run() -> Run:
    return Run(
        id=new_id(),
        kind="target",
        name="deploy",
        environment="staging",
        params={},
        argv=["make", "deploy"],
        command="make deploy",
        actor="tester",
        started="2026-09-05T00:00:00Z",
    )


# --- a run that stops and waits for a password ---


def test_ansible_s_own_prompts_are_recognised():
    for text, expected in (
        ("Vault password: ", "Vault password:"),
        ("Vault password (prod): ", "Vault password (prod):"),
        ("BECOME password: ", "BECOME password:"),
        ("SUDO password[defaults to SSH password]: ", "SUDO password[defaults to SSH password]:"),
    ):
        assert runner._prompt_in(text) == expected


def test_a_playbook_printing_the_word_password_is_not_a_prompt():
    """A bare `password:` in output would put the interface into a state nobody asked for."""
    for text in (
        "ok: [web1] => password: hunter2",
        "changed: [web1]",
        "TASK [Set the password] ****",
        "",
        "   ",
    ):
        assert runner._prompt_in(text) == ""


def test_nothing_can_be_answered_when_nothing_is_asking(tmp_path):
    active = runner.ActiveRun(_a_run(), RunStore(tmp_path), Redactor())
    assert not active.asking
    assert active.answer("hunter2000") is False
