from ordane.desktop import geometry


def test_the_defaults_come_back_when_nothing_was_saved(tmp_path):
    assert geometry.restore(tmp_path) == (*geometry.DEFAULT, False)


def test_a_saved_size_comes_back(tmp_path):
    geometry.save(tmp_path, 1400, 900, True)
    assert geometry.restore(tmp_path) == (1400, 900, True)


def test_a_size_too_small_to_be_a_choice_is_ignored(tmp_path):
    geometry.save(tmp_path, 40, 20, False)
    assert geometry.restore(tmp_path)[:2] == geometry.DEFAULT


def test_a_corrupt_file_is_a_default_rather_than_a_crash(tmp_path):
    (tmp_path / geometry.FILE_NAME).write_text("{not json", encoding="utf-8")
    assert geometry.restore(tmp_path) == (*geometry.DEFAULT, False)


def test_saving_where_it_cannot_be_written_does_not_raise(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory", encoding="utf-8")
    geometry.save(blocked / "state", 800, 600, False)
    assert geometry.restore(blocked / "state")[:2] == geometry.DEFAULT


# --- which of the rail and the menu this person keeps ---


def test_the_menu_alone_is_the_default(tmp_path):
    """The rail is a list of once-a-session actions; it is not what a page opens with."""
    assert geometry.navigation(tmp_path) == geometry.MENU


def test_a_choice_comes_back(tmp_path):
    geometry.save_navigation(tmp_path, geometry.MENU)
    assert geometry.navigation(tmp_path) == geometry.MENU


def test_a_choice_that_is_not_one_falls_back_rather_than_hiding_everything(tmp_path):
    geometry.save_navigation(tmp_path, "neither")
    assert geometry.navigation(tmp_path) == geometry.MENU


def test_the_size_and_the_choice_do_not_overwrite_each_other(tmp_path):
    geometry.save(tmp_path, 1400, 900, False)
    geometry.save_navigation(tmp_path, geometry.RAIL)
    assert geometry.restore(tmp_path) == (1400, 900, False)
    assert geometry.navigation(tmp_path) == geometry.RAIL


def test_every_choice_says_what_it_does():
    for _, name, meaning in geometry.NAVIGATION:
        assert name and meaning.endswith(".")


# --- sections somebody folded away, which should stay that way ---


def test_nothing_is_folded_until_somebody_folds_it(tmp_path):
    assert geometry.folded(tmp_path) == set()


def test_a_fold_comes_back(tmp_path):
    geometry.save_folded(tmp_path, "run-history", True)
    assert geometry.folded(tmp_path) == {"run-history"}


def test_unfolding_forgets_it_rather_than_recording_a_false(tmp_path):
    geometry.save_folded(tmp_path, "run-history", True)
    geometry.save_folded(tmp_path, "run-history", False)
    assert geometry.folded(tmp_path) == set()


def test_folds_do_not_overwrite_the_size_or_the_navigation(tmp_path):
    geometry.save(tmp_path, 1400, 900, False)
    geometry.save_navigation(tmp_path, geometry.RAIL)
    geometry.save_folded(tmp_path, "recent-runs", True)
    assert geometry.restore(tmp_path) == (1400, 900, False)
    assert geometry.navigation(tmp_path) == geometry.RAIL
    assert geometry.folded(tmp_path) == {"recent-runs"}


def test_a_folded_list_that_is_not_a_list_is_ignored(tmp_path):
    (tmp_path / geometry.FILE_NAME).write_text('{"folded": "run-history"}', encoding="utf-8")
    assert geometry.folded(tmp_path) == set()
