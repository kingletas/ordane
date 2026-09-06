import subprocess
from pathlib import Path

from ordane.core import plane


def a_checkout(tmp_path: Path, remote: str = "") -> Path:
    repo = tmp_path / "control-plane"
    repo.mkdir()
    (repo / "Makefile").write_text("help:\n\t@true\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, capture_output=True)
    if remote:
        subprocess.run(
            ["git", "remote", "add", "origin", remote], cwd=repo, check=True, capture_output=True
        )
    return repo


def test_a_declared_name_wins_and_is_portable(tmp_path):
    repo = a_checkout(tmp_path, "git@github.com:kingletas/other.git")
    identity = plane.of(repo, declared="example-deployment")
    assert identity.name == "example-deployment"
    assert identity.portable


def test_an_ssh_remote_reduces_to_owner_and_repository(tmp_path):
    repo = a_checkout(tmp_path, "git@github.com:you/control-plane.git")
    assert plane.of(repo).name == "you/control-plane"


def test_an_https_remote_reduces_to_the_same_name(tmp_path):
    repo = a_checkout(tmp_path, "https://github.com/you/control-plane.git")
    assert plane.of(repo).name == "you/control-plane"
    assert plane.of(repo).portable


def test_a_repository_with_no_remote_falls_back_to_the_folder(tmp_path):
    identity = plane.of(a_checkout(tmp_path))
    assert identity.name == "control-plane"
    assert identity.source == plane.FOLDER


def test_the_folder_name_is_reported_as_not_portable(tmp_path):
    """Two people can easily have two different repositories in folders of the
    same name, and a shared history would merge them silently."""
    identity = plane.of(a_checkout(tmp_path))
    assert not identity.portable
    assert "not portable" in identity.where_from


def test_a_declared_name_that_could_not_be_written_down_is_ignored(tmp_path):
    repo = a_checkout(tmp_path)
    assert plane.of(repo, declared="../../etc/passwd").source == plane.FOLDER


def test_a_folder_that_is_not_a_checkout_still_gets_a_name(tmp_path):
    (tmp_path / "plain").mkdir()
    assert plane.of(tmp_path / "plain").name == "plain"
