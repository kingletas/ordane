"""What the engine works out, all three front ends have to show.

The ledger is one engine and three renderings, and for a day the browser drew
an answer the engine had graded `problem` in the same type as a name and an
email address. A reader was told the archive that went live was not the archive
that was built, in the class used for de-emphasis, and every gate was green.

So these walk the values the engine produces and look for each one in each
rendering. A field added to `Answer` and rendered in two places out of three
fails here rather than being noticed by somebody reading a page months later.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ordane.insight import ledger
from ordane.presentation import language
from ordane.terminal import ledger as terminal_ledger
from ordane.web.app import Settings, create_app

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "written-by-audit-log.audit.jsonl"

MAKEFILE = "help: ## Show this help\n\t@true\n"
CONFIG = "control_plane: parity/plane\nenvironments:\n  allow: [staging]\n"


def a_plane(tmp_path: Path) -> Path:
    repo = tmp_path / "plane"
    repo.mkdir(exist_ok=True)
    (repo / "Makefile").write_text(MAKEFILE, encoding="utf-8")
    (repo / ".ordane.yml").write_text(CONFIG, encoding="utf-8")
    return repo


def tampered(tmp_path: Path) -> Path:
    """The fixture with one record edited: a broken chain, and a problem answer."""
    records = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    records[3]["artefact_sha256"] = "b" * 64
    path = tmp_path / "staging.audit.jsonl"
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
    )
    return path


@pytest.fixture
def book(tmp_path) -> ledger.Book:
    return ledger.gather(a_plane(tmp_path), [], [FIXTURE])[0]


@pytest.fixture
def broken(tmp_path) -> ledger.Book:
    return ledger.gather(a_plane(tmp_path), [], [tampered(tmp_path)])[0]


def web_pages(tmp_path: Path, path: Path) -> tuple[str, str]:
    """The listing and the newest deploy, as the browser renders them."""
    repo = a_plane(tmp_path)
    state = tmp_path / "state"
    client = TestClient(
        create_app(
            Settings(
                repo=repo,
                port=8710,
                state_dir=state,
                history_path=tmp_path / "none.csv",
                events_path=tmp_path / "none.jsonl",
                ledgers=(path,),
            )
        ),
        headers={"Host": "127.0.0.1:8710"},
    )
    listing = client.get("/ledger").text
    chain = ledger.read(path)
    release = ledger.deployments(chain)[0].release
    return listing, client.get(f"/ledger/{release}").text


def terminal_pages(book: ledger.Book, capsys) -> tuple[str, str]:
    terminal_ledger.books([book], 10)
    listing = capsys.readouterr().out
    terminal_ledger.deployment(book, book.deployments[0])
    return listing, capsys.readouterr().out


def desktop_text(book: ledger.Book) -> str:
    """Every label the page draws, as one string."""
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk

    from ordane.desktop.ledgerpage import LedgerPage

    Adw.init()
    page = LedgerPage()
    page.render([book])
    found: list[str] = []

    def walk(widget) -> None:
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label):
                found.append(child.get_text())
                found.extend(child.get_css_classes())
            else:
                found.extend(child.get_css_classes())
            walk(child)
            child = child.get_next_sibling()

    walk(page)
    return "\n".join(found)


# --- every answer, in all three ---


def test_every_answer_reaches_every_front_end(book, tmp_path, capsys):
    answers = ledger.answers(book.deployments[0], book.chain)
    listing, deploy = terminal_pages(book, capsys)
    web_listing, web_deploy = web_pages(tmp_path, FIXTURE)
    drawn = desktop_text(book)

    for answer in answers:
        assert answer.question in deploy, f"the terminal drops {answer.question!r}"
        assert answer.answer in deploy
        assert answer.question in web_deploy, f"the browser drops {answer.question!r}"
        assert answer.answer in web_deploy
        assert answer.question in drawn, f"the desktop drops {answer.question!r}"
        assert answer.answer in drawn


def test_every_exact_value_can_be_copied_from_every_front_end(book, tmp_path, capsys):
    """A checksum a reader cannot copy is a checksum they retype wrongly."""
    answers = ledger.answers(book.deployments[0], book.chain)
    exact = [value for answer in answers for value in answer.exact]
    assert exact, "the fixture should carry values worth copying"

    _, deploy = terminal_pages(book, capsys)
    _, web_deploy = web_pages(tmp_path, FIXTURE)
    drawn = desktop_text(book)
    for value in exact:
        assert value in deploy, f"the terminal drops {value[:16]}"
        assert value in web_deploy, f"the browser drops {value[:16]}"
        assert value in drawn, f"the desktop drops {value[:16]}"


def test_every_step_reaches_every_front_end(book, tmp_path, capsys):
    steps = ledger.steps(book.deployments[0])
    _, deploy = terminal_pages(book, capsys)
    _, web_deploy = web_pages(tmp_path, FIXTURE)
    drawn = desktop_text(book)
    for step in steps:
        assert step.name in deploy
        assert step.name in web_deploy
        assert step.name in drawn


# --- and the grading, which is the half that went missing ---


def test_a_problem_answer_is_graded_in_every_front_end(broken, tmp_path, capsys):
    """The engine grades an answer; a front end that renders the grade flat is lying quietly."""
    answers = ledger.answers(broken.deployments[0], broken.chain)
    problems = [a for a in answers if a.level == language.PROBLEM]
    assert problems, "a tampered ledger should produce at least one problem answer"

    _, deploy = terminal_pages(broken, capsys)
    assert terminal_ledger.LEVEL_MARK[language.PROBLEM] in deploy

    _, web_deploy = web_pages(tmp_path, broken.source.path)
    assert f"level-{language.PROBLEM}" in web_deploy, "the browser renders no severity"

    drawn = desktop_text(broken)
    assert "tint-bad" in drawn, "the desktop renders no severity"


def test_a_broken_chain_is_said_in_every_front_end(broken, tmp_path, capsys):
    listing, deploy = terminal_pages(broken, capsys)
    web_listing, web_deploy = web_pages(tmp_path, broken.source.path)
    drawn = desktop_text(broken)

    broken_word = language.chain_state(ledger.BROKEN).name
    for text in (listing, deploy, web_listing, web_deploy, drawn):
        assert broken_word in text or "breaks at line" in text.lower()
    # And the browser must not draw the alarm in the class it uses to play
    # something down, which is what it did until the parity check existed.
    assert "level-problem" in web_listing
    assert f"{ledger.BROKEN}" not in web_listing.split("level-")[0][-40:]


def test_the_browser_grades_an_intact_chain_as_such(tmp_path):
    """The quiet direction: an intact chain must not be graded as a problem."""
    listing, _deploy = web_pages(tmp_path, FIXTURE)
    assert "level-ok" in listing
    assert "level-problem" not in listing
