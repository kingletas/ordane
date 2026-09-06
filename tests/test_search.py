from dataclasses import dataclass

from ordane.core import search


@dataclass(frozen=True)
class FakeTarget:
    name: str
    description: str = ""


def names(matches):
    return [m.target.name for m in matches]


def test_the_word_itself_beats_the_same_letters_scattered():
    """The failure this classing exists to stop: scattered letters outranking a real name."""
    # "ale" opens `alert`, and is only a scattered subsequence of
    # `apply-release`: the a, the l and the e, in that order, far apart.
    targets = [FakeTarget("apply-release"), FakeTarget("alert")]
    assert names(search.rank(targets, "ale")) == ["alert", "apply-release"]


def test_an_exact_name_comes_before_one_that_merely_starts_with_it():
    targets = [FakeTarget("deploy-fast"), FakeTarget("deploy")]
    assert names(search.rank(targets, "deploy")) == ["deploy", "deploy-fast"]


def test_a_whole_word_in_the_name_beats_a_fragment_of_a_longer_one():
    # `patch` is a whole word in two of these and buried inside the third.
    targets = [FakeTarget("dispatcher"), FakeTarget("patch-hosts"), FakeTarget("patch")]
    assert names(search.rank(targets, "patch")) == ["patch", "patch-hosts", "dispatcher"]


def test_two_matches_of_the_same_class_keep_the_order_they_were_declared_in():
    # `bring-up` and `production-upload` both hold "up" the same way, so the
    # order they were declared in is the only thing left to decide it.
    targets = [FakeTarget("bring-up"), FakeTarget("production-upload"), FakeTarget("upload")]
    assert names(search.rank(targets, "up")) == ["upload", "bring-up", "production-upload"]


def test_the_description_still_matches_when_the_name_does_not():
    targets = [FakeTarget("maintenance-off", "Varnish restored and caches flushed")]
    assert names(search.rank(targets, "varnish")) == ["maintenance-off"]


def test_nothing_matches_when_nothing_matches():
    assert search.rank([FakeTarget("deploy")], "zzz") == []


def test_an_empty_needle_returns_everything_in_its_own_order():
    targets = [FakeTarget("b"), FakeTarget("a")]
    assert names(search.rank(targets, "  ")) == ["b", "a"]


def test_the_class_is_reported_so_the_interface_can_say_why():
    match = search.rank([FakeTarget("cache-clean")], "clean")[0]
    assert match.reason == "a word in the name"
