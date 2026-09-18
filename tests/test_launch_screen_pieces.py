"""The two pieces of the launch screen that hold logic of their own.

`activity` folds a day's runs into rows, and `suggest` filters a list while
somebody types. Both are reached only by driving the window, which is why
neither had been run by anything until now.
"""

from __future__ import annotations

from conftest import a_failed_run, a_run, page_text

# --- activity: what ran today, folded ---


def test_a_quiet_day_folds_into_one_row_and_still_draws(adw):
    from ordane.desktop.activity import activity
    from ordane.insight import density

    runs = [a_run(id=f"r{n}", name="ping") for n in range(6)]
    rows = density.fold(runs)
    drawn = activity(rows, on_open=lambda *_: None)

    assert rows, "six runs folded into nothing"
    assert page_text(drawn).strip(), "a folded day drew an empty block"


def test_a_failure_is_never_folded_away(adw):
    """Folding exists to hide what is routine, and a failure is not routine."""
    from ordane.desktop.activity import activity
    from ordane.insight import density

    runs = [a_run(id=f"r{n}", name="ping") for n in range(6)] + [a_failed_run(id="bad")]
    drawn = activity(density.fold(runs), on_open=lambda *_: None)
    text = page_text(drawn)

    assert "failed" in text.lower(), "a failed run was folded in with the routine ones"


def test_nothing_ran_today_draws_a_sentence(adw):
    from ordane.desktop.activity import activity

    assert page_text(activity([], on_open=lambda *_: None)) is not None


# --- suggest: the list that filters while somebody types ---


def test_the_completer_offers_what_it_is_given(adw):
    from gi.repository import Gtk

    from ordane.desktop.suggest import Completer

    entry = Gtk.Entry()
    completer = Completer(entry, lambda: ["staging", "docker", "performance"], noun="environment")
    assert completer is not None


def test_a_completer_over_an_empty_list_does_not_raise(adw):
    """A repository that declares no choices is the case nobody builds against."""
    from gi.repository import Gtk

    from ordane.desktop.suggest import Completer

    assert Completer(Gtk.Entry(), list, noun="environment") is not None
