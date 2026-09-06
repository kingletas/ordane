"""Cloning a control plane, and choosing which ref of it runs.

The URL check is the sharp one: `git clone 'ext::sh -c whoami'` runs a command
of the URL's choosing, so transports are allowed by name rather than blocked by
pattern, and anything unrecognised is a refusal instead of a try.
"""

import subprocess
from pathlib import Path

import pytest

from ordane.core import source


def _run(*arguments: str, cwd: Path) -> None:
    subprocess.run(list(arguments), cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A repository with two branches and a tag, cloneable from a path."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "Makefile").write_text("help:\n\t@echo hi\n", encoding="utf-8")
    _run("git", "init", "-q", "-b", "main", cwd=work)
    _run("git", "config", "user.email", "t@t", cwd=work)
    _run("git", "config", "user.name", "t", cwd=work)
    _run("git", "add", "-A", cwd=work)
    _run("git", "commit", "-qm", "first", cwd=work)
    _run("git", "tag", "v1", cwd=work)
    _run("git", "checkout", "-qb", "release", cwd=work)
    (work / "Makefile").write_text("help:\n\t@echo release\n", encoding="utf-8")
    _run("git", "commit", "-qam", "on release", cwd=work)
    _run("git", "checkout", "-q", "main", cwd=work)
    bare = tmp_path / "origin.git"
    _run("git", "clone", "-q", "--bare", str(work), str(bare), cwd=tmp_path)
    return bare


# --- which URLs may be handed to git ---


def test_an_ext_url_is_refused_because_it_names_a_command():
    # No space in it, so the scheme is what refuses it rather than the shape.
    refused = source.usable_url("ext::sh")
    assert refused.failed
    assert "https" in refused.message


@pytest.mark.parametrize(
    "url",
    [
        "ext::sh",
        "ext::sh -c id",
        "transport::anything",
        "../relative/path",
        "--upload-pack=touch /tmp/pwned",
        "https://host/a repo.git",
        "",
        "   ",
    ],
)
def test_anything_not_recognised_is_refused_rather_than_tried(url):
    assert source.usable_url(url).failed


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/repo.git",
        "file:///srv/planes/repo.git",
        "/srv/planes/repo.git",
        "http://internal/repo",
        "ssh://git@github.com/owner/repo.git",
        "git://host/repo.git",
        "git@github.com:owner/repo.git",
    ],
)
def test_the_four_transports_and_the_scp_form_are_accepted(url):
    assert source.usable_url(url).ok


def test_the_folder_is_the_last_segment_and_never_a_path():
    assert source.folder_for("https://github.com/owner/repo.git") == "repo"
    assert source.folder_for("git@github.com:owner/repo.git") == "repo"
    # `..` matches every character class you would write for a folder name.
    assert source.folder_for("https://host/..") == ""
    assert source.folder_for("https://host/.") == ""


# --- cloning ---


def test_a_clone_lands_where_it_was_asked_to(tmp_path, origin):
    into = tmp_path / "planes"
    done = source.clone(str(origin), into, name="control-plane")
    assert done.ok
    assert (into / "control-plane" / "Makefile").is_file()


def test_a_clone_over_something_that_exists_is_refused(tmp_path, origin):
    into = tmp_path / "planes"
    (into / "taken").mkdir(parents=True)
    assert source.clone(str(origin), into, name="taken").failed


def test_a_url_git_cannot_reach_reports_why_rather_than_raising(tmp_path):
    done = source.clone("https://127.0.0.1:1/nothing.git", tmp_path / "planes")
    assert done.failed
    assert done.detail


# --- choosing a ref ---


def _cloned(tmp_path: Path, origin: Path) -> Path:
    source.clone(str(origin), tmp_path / "planes", name="plane")
    return tmp_path / "planes" / "plane"


def test_every_branch_and_tag_is_listed_with_something_to_choose_by(tmp_path, origin):
    repo = _cloned(tmp_path, origin)
    listed = source.refs(repo)
    names = {ref.name for ref in listed}
    assert "main" in names
    assert "origin/release" in names
    # git drops the tab before an empty last field, and a tag's HEAD marker is
    # always empty: which is how every tag went missing the first time.
    assert "v1" in names
    assert {ref.kind for ref in listed} == {"branch", "remote", "tag"}
    # `refs/remotes/origin/HEAD` shortens to a bare `origin` and is not a ref
    # anybody chooses.
    assert "origin" not in names
    current = [ref for ref in source.refs(repo) if ref.current]
    assert [ref.name for ref in current] == ["main"]
    assert all(ref.commit and ref.when for ref in source.refs(repo))


def test_a_remote_branch_is_checked_out_as_one_that_tracks_it(tmp_path, origin):
    repo = _cloned(tmp_path, origin)
    assert source.switch(repo, "origin/release").ok
    listed = {ref.name: ref for ref in source.refs(repo)}
    assert listed["release"].current
    assert "release" in (repo / "Makefile").read_text(encoding="utf-8")


def test_a_tag_can_be_checked_out(tmp_path, origin):
    repo = _cloned(tmp_path, origin)
    assert source.switch(repo, "v1").ok


def test_switching_over_uncommitted_work_is_refused_rather_than_deciding(tmp_path, origin):
    repo = _cloned(tmp_path, origin)
    (repo / "Makefile").write_text("help:\n\t@echo mine\n", encoding="utf-8")
    refused = source.switch(repo, "origin/release")
    assert refused.failed
    assert "uncommitted" in refused.message
    assert "mine" in (repo / "Makefile").read_text(encoding="utf-8")


def test_a_ref_that_looks_like_a_flag_is_refused(tmp_path, origin):
    assert source.switch(_cloned(tmp_path, origin), "--orphan").failed


def test_a_ref_that_does_not_exist_says_so(tmp_path, origin):
    assert source.switch(_cloned(tmp_path, origin), "no-such-branch").failed


def test_a_fetch_brings_a_new_branch_into_view(tmp_path, origin):
    repo = _cloned(tmp_path, origin)
    _run("git", "branch", "later", "main", cwd=origin)
    assert "origin/later" not in {ref.name for ref in source.refs(repo)}
    assert source.fetch(repo).ok
    assert "origin/later" in {ref.name for ref in source.refs(repo)}


def test_none_of_this_raises_outside_a_checkout(tmp_path):
    assert source.refs(tmp_path) == []
    assert source.fetch(tmp_path).failed
    assert source.switch(tmp_path, "main").failed
