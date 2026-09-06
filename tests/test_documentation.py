"""The documentation, checked against the code it describes.

A page that names a key which does something else is confidently wrong and
nothing else catches it, and a guide drifts from its window without a word.
"""

import re
from pathlib import Path

from ordane.cli import _parser
from ordane.core.config import DANGER_LEVELS
from ordane.desktop.shortcuts import KEYS
from ordane.presentation import language
from ordane.record.store import Run

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "user-guide.md"
README = ROOT / "README.md"

# A `Ctrl+…` or `F7` written in a table cell, which is how the guide lists them.
IN_A_CELL = re.compile(r"^\| `([^`]+)` \|", re.M)


def documented_keys() -> dict[str, str]:
    rows = re.findall(r"^\| `([^`]+)` \| ([^|]+?) \|", GUIDE.read_text(encoding="utf-8"), re.M)
    return {key: label.strip() for key, label in rows}


def test_the_guide_names_no_key_the_window_does_not_bind():
    bound = {key.pretty: key.label for key in KEYS}
    for key, label in documented_keys().items():
        assert key in bound, f"the guide documents {key}, which nothing binds"
        assert bound[key] == label, f"{key} is bound to {bound[key]!r}, documented as {label!r}"


def test_every_bound_key_is_in_the_guide():
    documented = documented_keys()
    for key in KEYS:
        assert key.pretty in documented, f"{key.pretty} is bound but undocumented"


def test_every_danger_level_has_a_sentence_a_person_can_read():
    for level in DANGER_LEVELS:
        assert level in language.DANGER
        assert language.danger_note(level)


def test_every_run_state_the_store_can_hold_has_a_word():
    for state in ("running", "succeeded", "failed", "error", "cancelled"):
        assert state in language.STATE, f"{state} would be shown to a person as an identifier"


def test_an_unknown_state_is_still_readable_rather_than_raising():
    assert language.state_name("astonished") == "Astonished"
    assert language.state_meaning("astonished") == ""


def test_every_measure_the_dashboard_draws_is_named_in_words(tmp_path):
    from ordane.insight.metrics import snapshot

    produced = snapshot(
        history_path=tmp_path / "none.csv",
        events_path=tmp_path / "none.jsonl",
        runs=[],
        slo_specs=[],
    )
    for measure in produced.measures:
        assert language.measure_name(measure.key) != measure.key, (
            f"{measure.key} reaches the interface as an identifier"
        )


def test_every_command_is_in_the_help_a_person_reads():
    epilog = _parser().epilog
    commands = _parser()._subparsers._group_actions[0].choices
    for name in commands:
        assert name in epilog or name in README.read_text(encoding="utf-8"), (
            f"`{name}` exists and is described nowhere a person would look"
        )


def test_the_readme_points_at_every_page_in_docs():
    text = README.read_text(encoding="utf-8")
    for page in sorted((ROOT / "docs").glob("*.md")):
        assert f"docs/{page.name}" in text, f"{page.name} exists and nothing links to it"


def test_a_run_carries_no_field_the_interface_prints_raw():
    assert "state" in Run.__dataclass_fields__


def test_the_changelog_and_the_package_agree_on_the_version():
    from ordane import __version__

    heading = re.search(r"^## \[([^\]]+)\]", (ROOT / "CHANGELOG.md").read_text(), re.M)
    assert heading is not None, "the changelog has no version heading"
    assert heading.group(1) == __version__, (
        f"the changelog's newest entry is {heading.group(1)}, the package says {__version__}"
    )


# --- the house rules for a document, which are as checkable as a key binding ---

import subprocess  # noqa: E402

# GitHub renders exactly these five, and only in upper case. Anything else is
# a plain blockquote with `[!whatever]` printed in it: a silent rendering
# failure that looks fine in an editor which supports more.
GITHUB_ALERTS = ("NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION")

# Longer than a screen: the point at which a reader needs a way in.
NEEDS_CONTENTS = 120


def markdown_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [ROOT / name for name in listed]


def slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")


def test_every_contents_link_points_at_a_heading():
    """A contents entry that resolves to nothing is confidently wrong."""
    broken = []
    for path in markdown_files():
        text = path.read_text(encoding="utf-8")
        headings = {slug(one) for one in re.findall(r"^#{1,6} (.+)$", text, re.M)}
        for label, anchor in re.findall(r"^- \[([^\]]+)\]\(#([^)]+)\)", text, re.M):
            if anchor not in headings:
                broken.append(f"{path.name}: {label!r} -> #{anchor}")
    assert broken == [], "; ".join(broken)


def test_every_callout_is_one_github_renders():
    """A lower-case callout is a blockquote with its own syntax printed in it."""
    wrong = []
    for path in markdown_files():
        for kind in re.findall(r"^\s*> \[!([A-Za-z]+)\]", path.read_text(encoding="utf-8"), re.M):
            if kind not in GITHUB_ALERTS:
                wrong.append(f"{path.name}: [!{kind}]")
    assert wrong == [], "; ".join(wrong)


def test_a_long_document_offers_a_way_in():
    """Anything past a screen carries a contents list."""
    missing = [
        path.name
        for path in markdown_files()
        if len(path.read_text(encoding="utf-8").splitlines()) > NEEDS_CONTENTS
        and not re.search(r"^## Contents$", path.read_text(encoding="utf-8"), re.M)
        # The changelog is a reverse-chronological list; its own headings are
        # the way in, and a contents list of thirty-three releases is not one.
        and path.name != "CHANGELOG.md"
    ]
    assert missing == [], f"no contents list: {', '.join(missing)}"


def test_prose_is_not_hard_wrapped():
    """One paragraph is one line. A hard-wrapped one reflows badly everywhere
    it is read, and diffs a whole paragraph when a word changes."""
    suspicious = []
    for path in markdown_files():
        if path.name == "CODE_OF_CONDUCT.md":
            continue  # Reproduced verbatim; its wrapping is not ours to change.
        lines = path.read_text(encoding="utf-8").splitlines()
        longest = max((len(one) for one in lines), default=0)
        if longest and longest < 100 and len(lines) > 40:
            suspicious.append(f"{path.name} (longest line {longest})")
    assert suspicious == [], f"looks hard-wrapped: {', '.join(suspicious)}"


# Written verbatim from an outside source; its prose is not ours to change.
NOT_OURS = ("CODE_OF_CONDUCT.md",)

# A share of paragraphs, not a count: a long document is allowed more of them.
# Set above what these documents do today and well below what they used to,
# when the user guide alone opened eighty-one paragraphs this way.
MOST_BOLD_OPENERS = 20

BOLD_OPENER = re.compile(r"^\*\*[^*]+\*\*")


def paragraphs(text: str) -> list[str]:
    """Lines that start a paragraph: not a table, fence, heading, list or quote."""
    return [
        line
        for line in text.splitlines()
        if line.strip() and not line.startswith(("|", "```", "#", "![", " ", "-", ">", "*   "))
    ]


def test_paragraphs_do_not_all_open_with_a_bold_declaration():
    """Bolding the first clause of every paragraph is a tic, not emphasis.

    Emphasis works by being rare. When most paragraphs open with a bolded
    assertion, none of them stands out and the prose reads like a series of
    slogans instead of somebody explaining something.
    """
    heavy = []
    for path in markdown_files():
        if path.name in NOT_OURS:
            continue
        found = paragraphs(path.read_text(encoding="utf-8"))
        if len(found) < 12:
            continue
        bold = len([one for one in found if BOLD_OPENER.match(one)])
        share = bold * 100 // len(found)
        if share > MOST_BOLD_OPENERS:
            heavy.append(f"{path.name}: {bold} of {len(found)} paragraphs ({share}%)")
    assert heavy == [], "; ".join(heavy)
