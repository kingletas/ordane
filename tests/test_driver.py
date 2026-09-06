from ordane.core import driver


def test_a_repository_with_a_makefile_is_driven_by_make(tmp_path):
    (tmp_path / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
    assert driver.choose(tmp_path) == driver.MAKE


def test_a_repository_without_one_is_driven_by_ansible(tmp_path):
    (tmp_path / "playbooks").mkdir()
    assert driver.choose(tmp_path) == driver.ANSIBLE


def test_a_lowercase_makefile_counts(tmp_path):
    (tmp_path / "makefile").write_text("all:\n\t@true\n", encoding="utf-8")
    assert driver.choose(tmp_path) == driver.MAKE


def test_the_config_overrides_what_is_on_disk(tmp_path):
    (tmp_path / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
    assert driver.choose(tmp_path, "ansible") == driver.ANSIBLE


def test_a_name_that_is_not_a_driver_is_ignored_rather_than_obeyed(tmp_path):
    assert driver.choose(tmp_path, "terraform") == driver.ANSIBLE


def test_every_driver_says_what_it_reads_and_why_it_was_chosen():
    for one in driver.DRIVERS.values():
        assert one.surface and one.reason and one.executable
