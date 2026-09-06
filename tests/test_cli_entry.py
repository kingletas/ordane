"""What `ordane` does with the arguments it is given before a subcommand sees them.

`ordane`, `ordane --repo X` and `ordane app --repo X` all open the window,
which is what a desktop launcher needs. That rewriting has to leave the
top-level flags alone, and `--version` was swallowed by it until this existed.
"""

from __future__ import annotations

import pytest

from ordane import __version__, cli


def run(argv: list[str]) -> str:
    with pytest.raises(SystemExit) as exited:
        cli.main(argv)
    assert exited.value.code == 0
    return ""


def test_version_reports_the_version_and_where_it_runs_from(capsys):
    with pytest.raises(SystemExit) as exited:
        cli.main(["--version"])
    assert exited.value.code == 0
    printed = capsys.readouterr().out
    assert __version__ in printed
    # Three install paths can be on one machine, and PATH decides quietly
    # between them, so the answer has to include which one this is.
    assert "running from" in printed
    assert "ordane" in printed.split("running from")[1]


def test_help_is_still_the_top_level_help(capsys):
    with pytest.raises(SystemExit) as exited:
        cli.main(["--help"])
    assert exited.value.code == 0
    printed = capsys.readouterr().out
    assert "--version" in printed
    assert "doctor" in printed


@pytest.mark.parametrize("flag", ["-h", "--help", "--version"])
def test_a_top_level_flag_is_never_treated_as_an_app_argument(flag, capsys):
    """The bug this catches: `ordane --version` became `ordane app --version`."""
    with pytest.raises(SystemExit) as exited:
        cli.main([flag])
    assert exited.value.code == 0, f"{flag} was swallowed by the app shortcut"
