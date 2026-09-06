import subprocess
from pathlib import Path

from ordane.core import repository


def _git(where, *arguments: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *arguments],
        cwd=where,
        check=True,
        capture_output=True,
    )


def a_checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "plane"
    repo.mkdir()
    (repo / "Makefile").write_text("help:\n\t@true\n", encoding="utf-8")
    for command in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "-A"],
        ["git", "commit", "-qm", "first"],
    ):
        subprocess.run(command, cwd=repo, check=True, capture_output=True)
    return repo


def test_a_folder_that_is_not_a_checkout_says_nothing(tmp_path):
    state = repository.read(tmp_path)
    assert not state.is_git
    assert state.summary == ""


def test_a_clean_checkout_names_its_branch(tmp_path):
    state = repository.read(a_checkout(tmp_path))
    assert state.is_git
    assert state.branch == "main"
    assert not state.dirty
    assert state.summary == "main · clean"


def test_an_uncommitted_change_is_reported(tmp_path):
    repo = a_checkout(tmp_path)
    (repo / "Makefile").write_text("help:\n\t@echo changed\n", encoding="utf-8")
    state = repository.read(repo)
    assert state.dirty
    assert state.summary == "main · uncommitted changes"


def test_an_untracked_file_counts_as_a_change(tmp_path):
    repo = a_checkout(tmp_path)
    (repo / "new.yml").write_text("---\n", encoding="utf-8")
    assert repository.read(repo).dirty


def test_a_detached_head_says_so_rather_than_naming_a_branch(tmp_path):
    repo = a_checkout(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-q", head], cwd=repo, check=True, capture_output=True)
    state = repository.read(repo)
    assert state.detached
    assert state.summary.startswith("detached HEAD")


def test_a_broken_checkout_is_reported_as_no_checkout_rather_than_raising(tmp_path):
    repo = tmp_path / "plane"
    (repo / ".git").mkdir(parents=True)
    assert repository.read(repo) == repository.Checkout()


# --- the commit, which is what lets a lead time ever come from a run ---


def test_a_checkout_names_the_commit_it_is_on(tmp_path):
    state = repository.read(a_checkout(tmp_path))
    assert state.commit
    assert len(state.commit) >= 7
    assert all(character in "0123456789abcdef" for character in state.commit)


def test_a_folder_that_is_not_a_checkout_has_no_commit(tmp_path):
    assert repository.read(tmp_path).commit == ""


# --- how far behind the remote, which decides nothing and says something ---


def test_a_checkout_with_no_upstream_is_not_behind_anything(tmp_path):
    assert repository.read(a_checkout(tmp_path)).behind == 0


def test_being_behind_is_counted_and_said(tmp_path):
    (tmp_path / "origin").mkdir()
    origin = a_checkout(tmp_path / "origin")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    (origin / "later.txt").write_text("more\n", encoding="utf-8")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "one more")
    _git(clone, "fetch", "-q")
    state = repository.read(clone)
    assert state.behind == 1
    assert "1 behind the remote" in state.summary
