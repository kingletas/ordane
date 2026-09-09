"""Adding to a choice list is a write into somebody's repository, so it refuses.

Every case here is a way the write could go wrong, and each one is a refusal
with a reason rather than a correction: a console that quietly renamed a file
would leave somebody looking for the name they typed.
"""

from __future__ import annotations

import pytest

from ordane.core import choices
from ordane.core.config import Param

A_PATCH = "--- a/app/code/Foo.php\n+++ b/app/code/Foo.php\n@@ -1 +1 @@\n-old\n+new\n"


@pytest.fixture
def patches(tmp_path):
    (tmp_path / "patches").mkdir()
    return tmp_path


def a_source(repo):
    return choices.source_for(Param(name="patch", choices_from="patches"), repo)


def test_the_patches_list_is_a_directory_that_can_be_added_to(patches):
    source = a_source(patches)
    assert source is not None
    assert source.suffix == ".patch"
    assert source.writable


def test_a_literal_list_has_nowhere_to_add_to(tmp_path):
    """`choices: [present, absent]` is the recipe's own vocabulary, not a folder."""
    param = Param(name="state", choices=["present", "absent"])
    assert choices.source_for(param, tmp_path) is None


def test_a_glob_names_its_folder_and_its_extension(tmp_path):
    (tmp_path / "releases").mkdir()
    source = choices.source_for(Param(name="release", choices_from="glob:releases/*"), tmp_path)
    assert source.directory == tmp_path / "releases"
    assert source.suffix == ""


def test_a_pasted_patch_lands_where_the_list_is_read_from(patches):
    path = choices.add(a_source(patches), "MDVA-99999", A_PATCH)
    assert path == patches / "patches" / "MDVA-99999.patch"
    assert path.read_text().endswith("+new\n")


def test_the_file_is_readable_and_not_executable(patches):
    path = choices.add(a_source(patches), "MDVA-99999", A_PATCH)
    assert path.stat().st_mode & 0o777 == 0o644


def test_a_name_that_would_leave_the_directory_is_refused(patches):
    with pytest.raises(choices.AddError, match="A name may hold"):
        choices.add(a_source(patches), "../../etc/cron.d/evil", A_PATCH)


def test_a_name_with_a_slash_in_it_is_refused(patches):
    with pytest.raises(choices.AddError, match="A name may hold"):
        choices.add(a_source(patches), "sub/MDVA-1", A_PATCH)


def test_an_empty_name_is_refused(patches):
    with pytest.raises(choices.AddError, match="A name may hold"):
        choices.add(a_source(patches), "   ", A_PATCH)


def test_a_name_already_on_disk_is_never_overwritten(patches):
    choices.add(a_source(patches), "MDVA-99999", A_PATCH)
    with pytest.raises(choices.AddError, match="already there"):
        choices.add(a_source(patches), "MDVA-99999", A_PATCH)


def test_an_empty_paste_is_refused(patches):
    with pytest.raises(choices.AddError, match="Nothing was pasted"):
        choices.add(a_source(patches), "MDVA-99999", "   \n\n")


def test_something_that_is_not_a_patch_is_refused(patches):
    """A paste that missed the diff is the likeliest mistake here."""
    with pytest.raises(choices.AddError, match="does not look like a patch"):
        choices.add(a_source(patches), "MDVA-99999", "I meant to copy the diff\n")


def test_a_git_format_patch_is_accepted(patches):
    body = "From 9b1c commit\nSubject: [PATCH] fix\n\ndiff --git a/x b/x\n"
    assert choices.add(a_source(patches), "MDVA-99999", body).exists()


def test_a_missing_directory_is_refused_rather_than_created(tmp_path):
    """A typo'd `choices_from` would otherwise scatter folders through a repo."""
    with pytest.raises(choices.AddError, match="not a directory"):
        choices.add(a_source(tmp_path), "MDVA-99999", A_PATCH)


def test_the_new_name_is_then_one_of_the_choices(patches):
    from ordane.core import command

    param = Param(name="patch", choices_from="patches")
    assert command.choices_for(param, None, patches) == []
    choices.add(a_source(patches), "MDVA-99999", A_PATCH)
    assert command.choices_for(param, None, patches) == ["MDVA-99999"]
