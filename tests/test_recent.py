from pathlib import Path

from ordane.core import recent


def a_repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    (repo / "Makefile").write_text("help:\n\t@true\n", encoding="utf-8")
    return repo


def test_nothing_is_remembered_before_anything_is_opened(tmp_path):
    assert recent.last(tmp_path / "state") is None
    assert recent.remembered(tmp_path / "state") == []


def test_the_last_repository_comes_back(tmp_path):
    state = tmp_path / "state"
    repo = a_repo(tmp_path, "plane")
    recent.remember(state, repo)
    assert recent.last(state) == repo


def test_the_newest_is_first_and_a_repeat_moves_rather_than_duplicates(tmp_path):
    state = tmp_path / "state"
    one, two = a_repo(tmp_path, "one"), a_repo(tmp_path, "two")
    recent.remember(state, one)
    recent.remember(state, two)
    recent.remember(state, one)
    assert recent.remembered(state) == [one, two]


def test_the_list_does_not_grow_without_end(tmp_path):
    state = tmp_path / "state"
    for index in range(recent.LIMIT + 3):
        recent.remember(state, a_repo(tmp_path, f"plane{index}"))
    assert len(recent.remembered(state)) == recent.LIMIT


def test_a_repository_that_has_moved_is_left_out_rather_than_offered(tmp_path):
    state = tmp_path / "state"
    repo = a_repo(tmp_path, "plane")
    recent.remember(state, repo)
    (repo / "Makefile").unlink()
    assert recent.remembered(state) == []
    assert recent.last(state) is None


def test_one_can_be_forgotten_without_losing_the_others(tmp_path):
    state = tmp_path / "state"
    one, two = a_repo(tmp_path, "one"), a_repo(tmp_path, "two")
    recent.remember(state, one)
    recent.remember(state, two)
    recent.forget(state, two)
    assert recent.remembered(state) == [one]


def test_a_state_directory_that_cannot_be_written_does_not_raise(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory", encoding="utf-8")
    recent.remember(blocked / "state", a_repo(tmp_path, "plane"))
    assert recent.remembered(blocked / "state") == []
