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


def written_in_a_newer_format(tmp_path: Path) -> Path:
    """The fixture re-chained in a record format this reader does not know."""
    records = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    previous, rows = ledger.GENESIS, []
    for record in records:
        rebuilt = {**record, "schema": ledger.SCHEMA + 1, "prev_hash": previous}
        rebuilt.pop("hash", None)
        rebuilt["hash"] = ledger.record_hash(rebuilt)
        previous = rebuilt["hash"]
        rows.append(json.dumps(rebuilt, sort_keys=True))
    path = tmp_path / "staging.audit.jsonl"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
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


def desktop_answer_tints(book: ledger.Book) -> dict[str, set[str]]:
    """Each answer cell the page drew: the question it asks, and the tints inside it."""
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk

    from ordane.desktop.ledgerpage import LedgerPage

    Adw.init()
    page = LedgerPage()
    page.render([book])
    cells: dict[str, set[str]] = {}

    def inside(widget) -> tuple[list[str], set[str]]:
        texts: list[str] = []
        classes: set[str] = set()
        child = widget.get_first_child()
        while child is not None:
            classes.update(child.get_css_classes())
            if isinstance(child, Gtk.Label):
                texts.append(child.get_text())
            deeper_texts, deeper_classes = inside(child)
            texts.extend(deeper_texts)
            classes.update(deeper_classes)
            child = child.get_next_sibling()
        return texts, classes

    def walk(widget) -> None:
        child = widget.get_first_child()
        while child is not None:
            if "answer" in child.get_css_classes():
                texts, classes = inside(child)
                if texts:
                    cells[texts[0]] = {c for c in classes if c.startswith("tint-")}
            walk(child)
            child = child.get_next_sibling()

    walk(page)
    return cells


def web_answer_row(page: str, question: str) -> str:
    """The one table row that answers this question, and nothing after it."""
    start = page.index(question)
    return page[start : page.index("</tr>", start)]


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


def terminal_answer_marks(deploy: str, answers) -> dict[str, str]:
    """What the terminal actually printed in front of each answer."""
    marks: dict[str, str] = {}
    for line in deploy.splitlines():
        for answer in answers:
            if answer.question in line and answer.question not in marks:
                marks[answer.question] = line.split(answer.question)[0].strip()
    return marks


def drawn_one_way_per_level(observed: dict, answers) -> None:
    """Two answers graded alike look alike, and two graded differently do not.

    The expectation is never looked up in the front end's own table, which is
    what a test of a lookup table is worth nothing: it would agree with any
    value put there. What it asks instead is that the engine's grades survive
    the rendering as distinctions.
    """
    levels = {answer.level for answer in answers}
    assert len(levels) > 1, "this fixture grades everything the same, so nothing is proved"

    marks: dict[str, set] = {}
    for answer in answers:
        assert answer.question in observed, f"nothing was drawn for {answer.question!r}"
        marks.setdefault(answer.level, set()).add(observed[answer.question])

    for level, drawn in marks.items():
        assert len(drawn) == 1, f"{level} answers are drawn {len(drawn)} different ways"

    seen: dict = {}
    for level, drawn in marks.items():
        mark = next(iter(drawn))
        assert mark not in seen, f"{level} and {seen[mark]} answers are drawn identically"
        seen[mark] = level


def test_every_answer_carries_its_own_grade_in_every_front_end(broken, tmp_path, capsys):
    """Not that the page shows an alarm somewhere: that this answer shows this grade.

    This asked whether a problem marker appeared anywhere on the page. The break
    banner and the untrusted steps supply one, so every answer could be drawn
    flat and it still passed. Proved by regrading each front end in turn and
    watching the suite stay quiet.
    """
    answers = ledger.answers(broken.deployments[0], broken.chain)
    assert any(a.level == language.PROBLEM for a in answers), "a tampered ledger grades nothing"

    _, deploy = terminal_pages(broken, capsys)
    _, web_deploy = web_pages(tmp_path, broken.source.path)
    tints = desktop_answer_tints(broken)

    drawn_one_way_per_level(terminal_answer_marks(deploy, answers), answers)
    drawn_one_way_per_level({q: frozenset(t) for q, t in tints.items()}, answers)

    # The browser names the engine's own word for the grade, so this one can be
    # checked exactly rather than by distinction.
    for answer in answers:
        row = web_answer_row(web_deploy, answer.question)
        assert f'class="level-{answer.level}"' in row, f"the browser misgrades {answer.question!r}"


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


def test_a_newer_format_is_named_in_every_front_end(tmp_path, capsys):
    """A notice is not an Answer, a Step or a Timing, so nothing above walks it.

    The desktop was the front end that did not draw it: the fields it could not
    read came back empty under a green chain, which is the quiet failure this
    notice exists to prevent.
    """
    path = written_in_a_newer_format(tmp_path)
    book = ledger.gather(a_plane(tmp_path), [], [path])[0]
    said = language.newer_format(book.chain.newer_schema)
    assert book.chain.newer_schema > ledger.SCHEMA, "the fixture is not in a newer format"

    listing, _ = terminal_pages(book, capsys)
    web_listing, _ = web_pages(tmp_path, path)
    drawn = desktop_text(book)

    assert said in listing, "the terminal says nothing about a newer format"
    assert said in web_listing, "the browser says nothing about a newer format"
    assert said in drawn, "the desktop says nothing about a newer format"
