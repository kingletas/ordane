"""Typing narrows a list; the ranking and the choice of field are decided here.

These are decisions rather than widgets, which is why they live beside the
choice list and not in the form. The widget is driven in the window smoke: a
popover is its own surface and never appears in a screenshot of the window.
"""

from __future__ import annotations

from ordane.core.choices import matches, worth_completing

PATCHES = [
    "M2PL-6611",
    "MDVA-43395",
    "MDVA-38632",
    "MC-42528",
    "mdva-lowercase",
]


def test_nothing_typed_leaves_the_whole_list():
    assert matches("", PATCHES) == PATCHES


def test_what_starts_with_the_typing_comes_first():
    """`MC-42528` holds `M` too, and is not what somebody typing `MD` wants."""
    found = matches("MD", PATCHES)
    assert found[0].startswith("MDVA")
    assert found == ["MDVA-43395", "MDVA-38632", "mdva-lowercase"]


def test_something_in_the_middle_still_matches():
    assert matches("43395", PATCHES) == ["MDVA-43395"]


def test_case_is_ignored_in_both_directions():
    assert matches("mdva-4", PATCHES) == ["MDVA-43395"]
    assert matches("LOWERCASE", PATCHES) == ["mdva-lowercase"]


def test_surrounding_space_is_ignored():
    assert matches("  MC ", PATCHES) == ["MC-42528"]


def test_nothing_matching_returns_nothing_rather_than_everything():
    assert matches("MDVA-99999", PATCHES) == []


def test_a_short_list_of_words_is_picked_from_not_typed_into():
    """`present` or `absent` is quicker to see than to type."""
    assert not worth_completing(["present", "absent"], allow_other=False)


def test_a_long_list_is_typed_into():
    assert worth_completing([str(n) for n in range(63)], allow_other=False)


def test_a_list_that_can_be_added_to_is_always_typed_into():
    """However short: a dropdown has nowhere to offer the one that is missing."""
    assert worth_completing(["a", "b"], allow_other=False, can_add=True)


def test_an_empty_folder_still_offers_the_field():
    assert worth_completing([], allow_other=False, can_add=True)


def test_free_text_with_hints_is_typed_into():
    assert worth_completing(["main"], allow_other=True)


def test_free_text_with_no_hints_and_nowhere_to_add_is_a_plain_field():
    assert not worth_completing([], allow_other=True)
