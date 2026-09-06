"""Drives the real window through every page, and saves what it drew.

A window cannot be reviewed from its source. This opens a control plane for
real, walks the pages, launches a run and follows it to the end, and writes PNGs
so the result can be looked at rather than reasoned about.

Every check prints `ok`, `FAIL` or `skip`; the exit status is the number that
failed. A check whose prerequisite is missing skips with the reason, because a
machine with less installed than a desktop is not a defect.

Drive what a person touches, not the method behind it: click the button, change
the page, press the key. Exercising a component while never taking the route to
it is how a working component ships behind a broken door.

Usage:
  uv run python scripts/gui-smoke.py [REPO] [SHOTS_DIR]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

# The run reads and writes a settings file, so it gets a config home of its
# own: driving the window must never leave the person who ran it pointed at a
# store that only existed for a test.
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="ordane-smoke-config-"))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402, after the versions above

from ordane.core import edit, identity, search, validation  # noqa: E402
from ordane.core import inventory as inventory_module  # noqa: E402
from ordane.desktop import geometry  # noqa: E402
from ordane.desktop import widgets as w  # noqa: E402
from ordane.desktop.app import ConsoleApplication, Settings  # noqa: E402
from ordane.desktop.menu import primary_menu  # noqa: E402
from ordane.desktop.shortcuts import KEYS  # noqa: E402
from ordane.desktop.sidebar import ENTRIES  # noqa: E402
from ordane.insight import export  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = ROOT / "examples" / "control-plane"

# The window is drawn at a size a person would actually use, because a layout
# check at a size nobody opens proves nothing about the layout.
# Wide enough that the rail and the page both fit in a font wider than this
# machine's. At 1170 px, which is what a CI runner gave, an 18px font makes
# them contend and libadwaita says so on every layout pass. Measured: 1170
# squeezes at 18px, 1320 is clean at 20px and squeezes at 22px.
WINDOW = (1320, 860)

# However the run goes, the process ends.
# A shared CI runner is several times slower than a laptop: this run took 90
# seconds here and five minutes there, and a deadline tuned to the laptop
# failed everything after it. Overridable, so a slow machine is not a patch.
# How long to let the window catch up with a thread that is filling it.
VIEW_WAIT = 30.0

DEADLINE_SECONDS = int(os.environ.get("SMOKE_DEADLINE", "600"))

# `ping` in the example finishes at once; the ceiling is for a slow machine.
RUN_WAIT = 20.0

failures: list[str] = []
skipped: list[str] = []

# Every warning GTK, libadwaita, GLib or Pango writes while the window is
# driven. Reported at the end as a check of its own: until now the run said
# "zero GTK warnings" because somebody grepped the output, which missed an
# `Adwaita-WARNING` entirely.
complaints: list[str] = []

_LOUD = (
    GLib.LogLevelFlags.LEVEL_WARNING
    | GLib.LogLevelFlags.LEVEL_CRITICAL
    | GLib.LogLevelFlags.LEVEL_ERROR
)


def _listen(level, fields, n_fields, _user_data):
    """Counts anything loud, and still prints it so a run can be read.

    `log_writer_default` takes three arguments in this binding, not four: with
    four it raises on the first warning, and a listener that throws is one that
    only works while there is nothing to hear.
    """
    if level & _LOUD:
        found = GLib.log_writer_format_fields(level, fields, True)
        complaints.append(" ".join(str(found).split())[:200])
    return GLib.log_writer_default(level, fields, n_fields)


# Every view carries the actor: the connection card at the foot of the rail,
# and the `BY` column on a run. These photographs are published, so the person
# who happened to run the smoke must not be in them. Patched here and nowhere
# else -- `identity.who()` reads the operating system precisely so a recorded
# run cannot be attributed to a name somebody set, and that stays true.
DOCUMENTED_ACTOR = identity.Actor(user="ada", uid=1000, host="example")
identity.who = lambda: DOCUMENTED_ACTOR


# What the runbook sequence checks. Named here so the skip path and the run path
# cannot drift apart: a check added below without a line here would be silently
# unaccounted for on a machine with no container engine.
RUNBOOK_CHECKS = (
    "a role imported before the run is not marked that way",
    "a run says what it told the outside world",
    "a target other runbooks lean on says which and how",
    "all three steps ran, in order",
    "and marks what is chosen while the run goes rather than before it",
    "and names the one that did not land",
    "and only the operation is recorded as a deploy",
    "and the launch holds all four, oldest first",
    "and the predicted reach says what it cannot promise",
    "every step carries the launch it belongs to",
    "the checks are recorded under their own kind",
    "the control plane's own checks gate the deploy",
    "the form says what the playbook is made of",
    "the run view says what it was part of",
    "then the precheck runs, and not the deploy",
    "while nothing failing is not called a failure",
)


def check(label: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'}  {label}")
    if not condition:
        failures.append(label)


def skip(label: str, why: str) -> None:
    """A check whose prerequisite is absent, which is not the same as a failure.

    A machine with no container engine cannot run the validation suite, and
    saying FAIL there reports the machine as a defect in the application. The
    distinction is what lets this run somewhere other than a desktop.
    """
    print(f"skip  {label}: {why}")
    skipped.append(label)


def pump(seconds: float) -> None:
    """Runs the main loop for a while, so the window can actually get on with it."""
    context = GLib.MainContext.default()
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if not context.iteration(False):
            time.sleep(0.01)


def until(predicate, seconds: float) -> bool:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if predicate():
            return True
        pump(0.1)
    return predicate()


def snapshot(window: Gtk.Widget, path: Path) -> None:
    """Draws the window to a PNG, so what it looks like can be looked at."""
    paintable = Gtk.WidgetPaintable.new(window)
    width, height = window.get_width(), window.get_height()
    if width <= 1 or height <= 1:
        check(f"{path.name}: the window has a size", False)
        return
    renderer = window.get_native().get_renderer()
    node = None
    for _ in range(15):
        holder = Gtk.Snapshot()
        paintable.snapshot(holder, width, height)
        node = holder.to_node()
        if node is not None:
            break
        pump(0.15)
    if node is None or renderer is None:
        # A mapped window that still draws nothing after being given frames is
        # usually a compositor that is not painting it: a locked screen looks
        # exactly like a broken window.
        check(f"{path.name}: something painted, is the screen locked?", False)
        return
    renderer.render_texture(node, None).save_to_png(str(path))
    print(f"ok    wrote {path.name} ({width}x{height})")


def rows_under(widget: Gtk.Widget, kind=Adw.ActionRow) -> list:
    """Every row of a kind below this widget, however deep the boxes go."""
    found = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, kind):
            found.append(child)
        found.extend(rows_under(child, kind))
        child = child.get_next_sibling()
    return found


def titles(widget: Gtk.Widget) -> list[str]:
    return [row.get_title() for row in rows_under(widget)]


def has_text(widget: Gtk.Widget, needle: str) -> bool:
    """Whether the needle appears in any label below this widget."""
    for label in rows_under(widget, Gtk.Label):
        if needle.lower() in label.get_text().lower():
            return True
    return False


def page(window) -> Gtk.Widget:
    """The page on screen. Every other page is still built, so a check that
    walks the whole window passes on rows nobody can see."""
    if window._surface.get_visible_child_name() == "broken":
        return window._broken
    return window._stack.get_visible_child()


def _menu_rows(menu) -> dict[str, str]:
    """Every action the primary menu offers, and the label it offers it under."""
    found = {}
    for section in range(menu.get_n_items()):
        link = menu.get_item_link(section, "section")
        if link is None:
            continue
        for row in range(link.get_n_items()):
            action = link.get_item_attribute_value(row, "action", None)
            label = link.get_item_attribute_value(row, "label", None)
            if action is not None and label is not None:
                found[action.get_string()] = label.get_string()
    return found


def _rail_rows() -> dict[str, str]:
    """The same, from the rail."""
    return {action: label for _, rows in ENTRIES for _, label, action in rows}


def check_the_two_lists_agree() -> None:
    """Preferences says the rail and the menu hold the same rows. Nothing checked it.

    They had drifted: one action was `Run this plane's own checks…` in the rail
    and `Check this control plane's own checks…` in the menu, and a third name
    was on the dialog it opened.
    """
    rail, menu = _rail_rows(), _menu_rows(primary_menu())
    shared = sorted(set(rail) & set(menu))
    disagreeing = [a for a in shared if rail[a] != menu[a]]
    check(
        f"the rail and the menu label their {len(shared)} shared rows the same",
        not disagreeing,
    )
    for action in disagreeing:
        print(f"      {action}: rail {rail[action]!r} vs menu {menu[action]!r}")

    # A label used twice in one surface is two doors with one sign on them.
    for where, rows in (("rail", rail), ("menu", menu)):
        labels = list(rows.values())
        repeated = sorted({one for one in labels if labels.count(one) > 1})
        check(f"no two {where} rows share a label", not repeated)
        for one in repeated:
            print(f"      {where}: {one!r}")

    # An icon that means two things in one list is the same defect, drawn.
    icons = [icon for _, rows in ENTRIES for icon, _, _ in rows]
    twice = sorted({one for one in icons if icons.count(one) > 1})
    check("no two rail rows share an icon", not twice)
    for one in twice:
        print(f"      {one}")


def drive(app, repo: Path, shots: Path) -> None:
    window = app.get_active_window()
    check("the window exists", window is not None)
    window.set_default_size(*WINDOW)
    window.present()
    pump(1.5)

    catalog = window._catalog
    check("`make help` was read", catalog is not None and bool(catalog.targets))
    check(
        "the environments came with it",
        catalog is not None and {"docker", "staging"} <= {e.name for e in catalog.environments},
    )
    check(
        "an environment with no inventory is reported as unusable",
        any(not e.usable for e in catalog.environments),
    )

    check_the_two_lists_agree()

    # --- the pages ---

    snapshot(window, shots / "01-health.png")
    check("the health page leads with a status card", _with_class(page(window), "status-card"))
    check("which says what state it is in", has_text(page(window), "needs attention"))
    check("and what it costs", has_text(page(window), "waiting on a source"))
    check("the environments are beside it", has_text(page(window), "environments"))
    check(
        "the delivery measures carry the names the industry uses",
        has_text(page(window), "change failure rate"),
    )
    check(
        "and a measure with no source says what would fill it, not `no data`",
        has_text(page(window), "setup needed") and not has_text(page(window), "no data"),
    )

    window.activate_action("win.page", GLib.Variant.new_string("actions"))
    pump(0.8)
    # `make help` is a subprocess, and a loaded machine can make it fail. When
    # it does, every check below reports a missing target instead of the one
    # thing that actually went wrong.
    if window._catalog_error:
        check(f"the repository stayed readable: {window._catalog_error}", False)

    listed = titles(page(window))
    check("the actions page lists the chosen group's targets", "deploy" in listed)
    check("a hidden target stays hidden", "help" not in listed)
    check("a dangerous target says what it does", has_text(page(window), "Customers see this"))
    # One group at a time: eleven targets scroll and forty do not, so the
    # column carries the rest rather than the page carrying all of them.
    check("the other groups are in the column rather than on the page", "ping" not in listed)
    check("and the column names them", has_text(page(window), "Fleet"))
    snapshot(window, shots / "02-actions.png")
    window._choose_group("Fleet")
    pump(0.5)
    check("choosing a group shows it", "ping" in titles(page(window)))
    window._choose_group("Release")
    pump(0.4)

    # --- search ---

    window.activate_action("win.find", None)
    pump(0.4)
    window._search.set_text("ping")
    pump(0.6)
    found = titles(page(window))
    check("searching narrows the list", "ping" in found and "flush-cache" not in found)
    check("the best match is first", bool(found) and found[0] == "ping")
    snapshot(window, shots / "03-search.png")

    window._search.set_text("zzzznothing")
    pump(0.5)
    check("a search with no match says so", has_text(page(window), "Nothing here is called"))
    window._search.set_text("")
    window.activate_action("win.back", None)
    pump(0.4)

    # --- the launch form ---

    target = catalog.target("activate")
    window._open_launch(target)
    pump(0.8)
    dialog = _dialog(window)
    check("the launch dialog opened", dialog is not None)
    if dialog is not None:
        check("it warns before a high-danger run", has_text(dialog, "customers see"))
        check("it asks for the environment name", has_text(dialog, "confirm"))
        check(
            "the preview holds no placeholder command",
            not has_text(dialog, "none available"),
        )
        check("the run options are there to be opened", has_text(dialog, "Run options"))
        # The declared Ansible settings have to be on the preview, not merely in
        # the environment: what is about to run is the thing a person reads here.
        check(
            "the preview shows the settings this plane declares",
            "ANSIBLE_ROLES_PATH=./roles" in dialog._preview.get_text(),
        )
        check(
            "and the command is still after them",
            dialog._preview.get_text().index("ANSIBLE_ROLES_PATH")
            < dialog._preview.get_text().index("make"),
        )
        # Asked of Ansible on a thread, so it arrives after the form does.
        reached = until(lambda: "builds on" in dialog._reach.get_text(), 45.0)
        check("the form says what the environment is made of, builder included", reached)
        if not reached:
            print(f"      reach said {dialog._reach.get_text()!r}")
            told = inventory_module.read(repo, "inventory/docker")
            print(f"      ansible said groups={[g.name for g in told.groups]!r}")
            print(f"      error={told.error!r} hint={told.hint[:120]!r}")
        check(
            "and says it is a prediction rather than a promise",
            "Predicted reach" in dialog._reach.get_text(),
        )
        snapshot(window, shots / "04-launch.png")
        dialog.close()
        pump(0.4)

    # --- a real run, followed to the end ---

    window._open_launch(catalog.target("ping"))
    pump(0.6)
    dialog = _dialog(window)
    if dialog is not None:
        dialog._on_run_clicked(None)
    pump(0.5)
    check("the run view opened", window._stack.get_visible_child_name() == "run")
    # One builder can package releases for several environments, so which host
    # made an artefact is not answerable from the environment name later.
    built = until(
        lambda: (
            window._runview._run is not None and window._runview._run.builder == "example-docker"
        ),
        VIEW_WAIT,
    )
    check("the run recorded the host it was built on", built)
    if not built and window._runview._run is not None:
        print(f"      builder was {window._runview._run.builder!r}")
    finished = until(
        lambda: window._runview._run is not None and window._runview._run.state != "running",
        RUN_WAIT,
    )
    check("the run finished", finished)
    # The run's state and the view are filled by different threads: waiting for
    # the first says nothing about the second, and on a slower machine the gap
    # is long enough to read.
    check(
        "its result was parsed, not just its exit code",
        until(lambda: has_text(window._runview, "ok"), VIEW_WAIT),
    )
    check(
        "and the empty-output notice is out of the way",
        until(lambda: not window._runview._placeholder.get_visible(), VIEW_WAIT),
    )
    # Hundreds of lines and no way to find one, until now.
    window._runview.find()
    window._runview._find.set_text("ok")
    found = until(
        lambda: bool(window._runview._matches) and "of" in window._runview._found.get_text(),
        VIEW_WAIT,
    )
    check("a run's output can be searched", found)
    if not found:
        print(f"      search said {window._runview._found.get_text()!r}")
    snapshot(window, shots / "05-run.png")
    window._runview._find.set_text("")
    pump(0.3)

    # A value worth taking away can be selected with the mouse. This was
    # refused for a year because a focused selectable label being destroyed
    # walked GTK through a disposed widget, so the header releases focus
    # before it rebuilds, and this drives exactly that sequence.
    picked = [
        label
        for label in rows_under(window._runview, Gtk.Label)
        if label.get_selectable() and label.get_text()
    ]
    check("a run's values can be selected", bool(picked))
    if picked:
        picked[0].grab_focus()
        picked[0].select_region(0, -1)
        pump(0.2)
        check("selecting one puts it in the buffer", picked[0].get_selection_bounds() is not None)
        window._runview._rebuild_header()
        pump(0.3)
        check("and rebuilding the header over a selection is quiet", True)

    # A run that printed nothing: the pane says which kind of silence it is.
    silent = window._runview._run
    window._runview.show(silent, "")
    pump(0.4)
    check(
        "a run that printed nothing says so rather than showing a black rectangle",
        window._runview._placeholder.get_visible()
        and "printed nothing" in window._runview._placeholder.get_text(),
    )

    # Run it again, from what it recorded.
    before = len(window._store.all(repo, plane=window._plane.name))
    window._relaunch(window._runview._run.id)
    finished = until(
        lambda: window._runview._run is not None and window._runview._run.state != "running",
        RUN_WAIT,
    )
    # The runner keeps every run it started; a finished one handed the view an
    # empty string and no stream, so a run you had just watched came back
    # saying it had printed nothing.
    watched = window._runview._run.id
    window._go("runs")
    pump(0.3)
    window._open_run(watched)
    pump(0.5)
    check(
        "re-opening a run you just watched still shows its output",
        not window._runview._placeholder.get_visible() and window._runview._text().strip() != "",
    )

    check("a recorded run can be run again", finished)
    check(
        "and the second one is recorded too",
        len(window._store.all(repo, plane=window._plane.name)) == before + 1,
    )

    window.activate_action("win.page", GLib.Variant.new_string("runs"))
    window._render(reread_catalog=False)
    pump(0.6)
    check("the finished run is in the history", "ping" in titles(page(window)))
    check("grouped under the day it happened on", has_text(page(window), "Today"))
    snapshot(window, shots / "06-runs.png")

    # --- the keyboard, and the sheet that documents it ---

    missing = [k.accelerator for k in KEYS if app.get_accels_for_action(k.action) == []]
    check(f"every shortcut is bound ({len(KEYS)} of them)", not missing)
    window.activate_action("win.shortcuts", None)
    pump(0.6)
    sheet = _dialog(window)
    check("the shortcuts sheet opened", sheet is not None)
    if sheet is not None:
        listed = titles(sheet)
        check("it lists every key in the table", all(k.label in listed for k in KEYS))
        snapshot(window, shots / "07-shortcuts.png")
        sheet.close()
        pump(0.3)

    # --- the window remembers itself, and can reach another control plane ---

    check(
        "the window opened at the size it was left",
        (window.get_width(), window.get_height()) != (0, 0),
    )
    window._on_close()
    saved = geometry.restore(window._settings.state_dir)
    check("and writes that size down on the way out", saved[0] > 0 and saved[1] > 0)

    others = window._others()
    check("a second control plane is reachable from the menu", isinstance(others, list))
    window._open_repository(repo.parent / "does-not-exist")
    pump(0.4)
    check(
        "and one that is not a control plane is refused rather than opened",
        len(app.get_windows()) == 1,
    )

    # --- the lock a second console can see ---

    from ordane.core import identity as identity_module
    from ordane.record.lock import Locks

    other = Locks(window._store.root, window._config.lock_scope)
    other.take(
        plane=window._plane.name,
        environment="docker",
        target="ping",
        actor=identity_module.who(),
        started="a moment ago",
    )
    check(
        "a second console holding the lock is visible to this one",
        window._runner.busy_with("docker", "ping") is not None,
    )
    window._open_launch(catalog.target("ping"))
    pump(0.5)
    held = _dialog(window)
    if held is not None:
        held._on_run_clicked(None)
        pump(0.6)
        held.close()
        pump(0.3)
    check(
        "and launching it again is refused rather than run twice",
        len(window._store.all(repo, plane=window._plane.name)) == before + 1,
    )
    check(
        "a different runbook against the same environment is still allowed",
        window._runner.busy_with("docker", "slow-ping") is None,
    )
    other.release(window._plane.name, "docker", "ping")
    check(
        "and releasing it lets the next one through",
        window._runner.busy_with("docker", "ping") is None,
    )

    # --- who the runs are recorded as, which a shared history depends on ---

    check("the console knows what it is running as", bool(window._actor.user))
    check(
        "the run was recorded against that account and machine",
        window._runview._run.actor == window._actor.name,
    )
    check(
        "the control plane has a portable name",
        window._plane.portable and "/" in window._plane.name,
    )
    check(
        "which is what the history is scoped by",
        has_text(window._plane_button, window._plane.name),
    )
    check("and root is not what this is running as", not window._actor.is_root)

    # --- the rail, which is a choice rather than what the window opens with ---

    check("the window does not open behind a rail", not window.split.get_show_sidebar())
    check(
        "and the header says which control plane without one",
        has_text(window._plane_button, window._plane.name),
    )
    window._choose_navigation(geometry.BOTH)
    pump(0.5)
    check("choosing the rail brings it back", window.split.get_show_sidebar())
    check("and it carries the connection card", has_text(window._sidebar, "Connected"))
    check("which names the checkout", has_text(window._sidebar, "git checkout"))
    # Waited for rather than slept on: a breakpoint applies on the next layout
    # pass, and a fixed pause makes this fail at random on a busy machine.
    window.set_default_size(760, 700)
    check(
        "a narrow window folds the rail away",
        until(lambda: window.split.get_collapsed(), 5.0),
    )
    snapshot(window, shots / "13-narrow.png")
    window.set_default_size(*WINDOW)
    check(
        "and a wide one brings it back",
        until(lambda: not window.split.get_collapsed(), 5.0),
    )

    # --- filtering the history ---

    window.activate_action("win.page", GLib.Variant.new_string("runs"))
    pump(0.5)
    check("the history leads with the most recent run", has_text(page(window), "Most recent"))
    window.activate_action("win.runs-filter", GLib.Variant.new_string("failed"))
    pump(0.6)
    check(
        "filtering to failures says there are none rather than showing nothing",
        has_text(page(window), "Nothing here has failed"),
    )
    window.activate_action("win.runs-filter", GLib.Variant.new_string("all"))
    pump(0.5)
    check("and clearing it brings the run back", "ping" in titles(page(window)))

    # --- folding, and the mouse buttons that step back through the pages ---

    section = next(
        (child for child in rows_under(page(window), w.Section)),
        None,
    )
    check("the run history is a section that folds", section is not None)
    if section is not None:
        # Clicked, not folded: calling `fold` directly is what let an inverted
        # click ship: the method worked and the button was a no-op both ways.
        section._toggle.emit("clicked")
        pump(0.4)
        check("clicking the heading hides the history", not section._revealer.get_reveal_child())
        check(
            "and the choice is written down",
            "run-history" in geometry.folded(window._settings.state_dir),
        )
        section._toggle.emit("clicked")
        pump(0.4)
        check("clicking it again brings it back", section._revealer.get_reveal_child())
        check(
            "and forgets the fold rather than recording a false",
            "run-history" not in geometry.folded(window._settings.state_dir),
        )

    # Deliberately not the estate: visiting it asks two databases, and this is
    # a test of where the pages go rather than of what they load.
    window.activate_action("win.page", GLib.Variant.new_string("actions"))
    pump(0.4)
    window.activate_action("win.go-back", None)
    pump(0.4)
    check(
        "back returns to the page before this one",
        window._stack.get_visible_child_name() == "runs",
    )
    window.activate_action("win.go-forward", None)
    pump(0.4)
    check(
        "and forward goes on again",
        window._stack.get_visible_child_name() == "actions",
    )
    window.activate_action("win.page", GLib.Variant.new_string("runs"))
    pump(0.3)

    # --- the rail and the menu are a choice, not a default ---

    window.activate_action("win.preferences", None)
    pump(0.7)
    prefs = _dialog(window)
    check("preferences opened", prefs is not None)
    if prefs is not None:
        snapshot(window, shots / "16-preferences.png")
        prefs._buttons[geometry.MENU].set_active(True)
        pump(0.5)
        check("menu only puts the rail away", not window.split.get_show_sidebar())
        check("and keeps the menu button", window._hamburger.get_visible())
        prefs._buttons[geometry.RAIL].set_active(True)
        pump(0.5)
        check("rail only brings it back", window.split.get_show_sidebar())
        check("and takes the menu button away", not window._hamburger.get_visible())
        prefs._buttons[geometry.BOTH].set_active(True)
        pump(0.4)
        check(
            "both keeps both",
            window.split.get_show_sidebar() and window._hamburger.get_visible(),
        )
        prefs.close()
        pump(0.3)
    check(
        "and the choice is remembered",
        geometry.navigation(window._settings.state_dir) == geometry.BOTH,
    )

    # --- the control plane's own checks, in the container it declares ---

    # The suite runs inside a container the repository declares, so a machine
    # with no engine cannot run it. The application already answers this; asking
    # it here is what stops an absent engine being reported as a broken feature.
    engine_missing = validation.available(window._config.validation)
    if engine_missing:
        for one in (
            "the checks dialog opened",
            "every declared check reported a state",
            "and they passed",
            "the suite is written into the run history",
            "its transcript is readable and leads with the summary",
        ):
            skip(one, engine_missing)
    else:
        window.activate_action("win.checks", None)
        pump(0.8)
        sheet = _dialog(window)
        check("the checks dialog opened", sheet is not None)
        if sheet is not None:
            check(
                "it names the image and says what the container is not allowed",
                has_text(sheet, "no network") and has_text(sheet, "read-only"),
            )
            sheet.start()
            until(lambda: not sheet._running, 180.0)
            pump(0.6)
            states = {name: badge.get_text() for name, badge in sheet._badges.items()}
            check(
                "every declared check reported a state", states and "NOT RUN" not in states.values()
            )
            passed = set(states.values()) == {"PASSED"}
            check("and they passed", passed)
            if not passed:
                # Say which one and why, rather than leaving a reader to guess at a
                # machine they cannot see. This cost four pushes.
                for name, state in states.items():
                    print(f"      {state:<8} {name}")
                for name, row in sheet._rows.items():
                    said = row.get_subtitle() or ""
                    if said:
                        print(f"      {name}: {said[:160]}")
            snapshot(window, shots / "23-checks.png")
            sheet.close()
            pump(0.6)
            # Evidence nobody wrote down is a claim: the window drew this result
            # and the history used to hold nothing about it.
            newest = window._store.all(repo, plane=window._plane.name)[0]
            check(
                "the suite is written into the run history",
                newest.kind == "checks" and newest.state == "succeeded",
            )
            check(
                "and it carries no labels, so it can never count as a deploy", newest.labels == {}
            )
            check(
                "its transcript is readable and leads with the summary",
                window._store.output(newest.id).startswith("3 of 3 passed"),
            )

    # --- a runbook that checks before and after ---

    # The runbook target declares `validate: true`, so this whole sequence needs
    # the same container engine the checks dialog does. Without it there is
    # nothing to report but the absence.
    if engine_missing:
        for one in RUNBOOK_CHECKS:
            skip(one, engine_missing)
    else:
        window.activate_action("win.page", GLib.Variant.new_string("actions"))
        pump(0.5)
        window._choose_group("Repo")
        pump(0.4)
        window._open_launch(window._catalog.target("check"))
        pump(0.8)
        leaned = _dialog(window)
        check(
            "a target other runbooks lean on says which and how",
            leaned is not None
            and has_text(leaned, "lean on this one")
            and has_text(leaned, "checks with this first"),
        )
        if leaned is not None:
            leaned.close()
            pump(0.4)

        # Ansible already composes; this reads the composition that is in the file.
        window._choose_group("Release")
        pump(0.4)
        window._open_launch(window._catalog.target("deploy"))
        pump(0.9)
        made = _dialog(window)
        check(
            "the form says what the playbook is made of",
            made is not None and has_text(made, "Made of"),
        )
        if made is not None:
            check(
                "and marks what is chosen while the run goes rather than before it",
                has_text(made, "RUN TIME") and has_text(made, "tasks/preflight.yml"),
            )
            check(
                "a role imported before the run is not marked that way",
                has_text(made, "example-role-deploy"),
            )
            check(
                "and the predicted reach says what it cannot promise",
                until(lambda: "chosen while the run goes" in made._reach.get_text(), 45.0),
            )
            snapshot(window, shots / "26-composition.png")
            made.close()
            pump(0.4)

        pump(0.4)
        before = len(window._store.all(repo, plane=window._plane.name))
        window._launch(window._catalog.target("deploy"), "docker", {"branch_name": "main"}, False)
        # The runbook asks for its own checks first, so a dialog opens before
        # anything is launched at all.
        pump(1.0)
        gate = _dialog(window)
        check("the control plane's own checks gate the deploy", gate is not None)
        if gate is not None:
            until(lambda: not gate._running, 240.0)
            pump(0.8)
            gate.close()
            pump(0.6)
        check(
            "then the precheck runs, and not the deploy",
            window._runview._run is not None and window._runview._run.name == "check",
        )
        until(lambda: window._sequence is None, 120.0)
        # Wait for the records rather than for the sequence flag: the last one is
        # written by the runner's own thread, and `check, deploy, check` is a
        # palindrome, so a racy read of it passes by luck.
        until(lambda: len(window._store.all(repo, plane=window._plane.name)) >= before + 3, 30.0)
        pump(0.4)
        newest = window._store.all(repo, plane=window._plane.name)[:3]
        check(
            "all three steps ran, in order",
            [(r.kind, r.name) for r in newest]
            == [("postcheck", "check"), ("target", "deploy"), ("precheck", "check")],
        )
        # Every notification in a real deploy is `failed_when: false`, so one that
        # never landed costs the deploy nothing and is invisible unless something
        # looks at what it said.
        window._open_run(newest[1].id)
        check(
            "a run says what it told the outside world",
            until(lambda: has_text(window._runview, "Told the outside world"), 10.0),
        )
        check(
            "and names the one that did not land",
            has_text(window._runview, "DID NOT LAND") and has_text(window._runview, "noibu"),
        )
        # `0 of 3 apps FAILED` is the healthiest answer there is, and it says FAILED.
        check(
            "while nothing failing is not called a failure",
            has_text(window._runview, "0 of 3 apps FAILED")
            and len([one for one in rows_under(window._runview) if "DID NOT LAND" in str(one)]) < 2,
        )
        snapshot(window, shots / "25-told.png")

        # The checks, the precheck, the operation and the postcheck are one launch:
        # without this the only thing relating them is the clock.
        launch = newest[1].sequence
        check("every step carries the launch it belongs to", bool(launch))
        steps = window._store.steps_of(launch)
        check(
            "and the launch holds all four, oldest first",
            [r.kind for r in steps] == ["checks", "precheck", "target", "postcheck"],
        )
        window._open_run(newest[1].id)
        pump(0.6)
        check(
            "the run view says what it was part of",
            has_text(window._runview, "Part of one launch"),
        )
        snapshot(window, shots / "24-launch.png")
        recorded = window._store.all(repo, plane=window._plane.name)
        check(
            "and only the operation is recorded as a deploy",
            all(
                not r.labels.get("deploy") for r in recorded if r.kind in ("precheck", "postcheck")
            ),
        )
        check(
            "the checks are recorded under their own kind", "precheck" in {r.kind for r in recorded}
        )

    # --- asking hosts a question, which changes nothing ---

    window.activate_action("win.environments", None)
    pump(0.7)
    manage = _dialog(window)
    asks = [
        button for button in rows_under(manage, Gtk.Button) if button.get_label() == "Check hosts"
    ]
    check("each usable environment can be asked whether it answers", len(asks) >= 1)
    if asks:
        asks[0].emit("clicked")
        pump(1.0)
        until(lambda: window._runview._run and window._runview._run.state != "running", 40.0)
        pump(0.5)
        asked = window._runview._run
        check("the question ran", asked is not None and asked.state == "succeeded")
        check("and it asked rather than instructed", "-m ping" in asked.command)
        # `ansible` prints no PLAY RECAP: without reading its per-host answers
        # the whole result was a wall of JSON with no panel over it.
        check(
            "the answer is read host by host rather than left as output",
            asked.result.has_recap and asked.result.ok >= 1,
        )
        check(
            "and a probe is neither a deploy nor a cutover",
            not asked.labels.get("deploy") and not asked.labels.get("cutover"),
        )
        snapshot(window, shots / "22-probe.png")

    # --- where the control plane comes from, and which ref of it runs ---

    window.activate_action("win.refs", None)
    pump(0.6)
    picker = _dialog(window)
    check("the ref picker opened", picker is not None)
    if picker is not None:
        check(
            "a folder that is not a checkout says so rather than showing nothing",
            has_text(picker, "not a git checkout"),
        )
        picker.close()
        pump(0.3)

    # Made into one, with a branch that widens the launch gate: which is the
    # whole reason this dialog is careful.
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the control plane")
    _git(repo, "checkout", "-qb", "wider")
    widened = (repo / ".ordane.yml").read_text(encoding="utf-8")
    (repo / ".ordane.yml").write_text(
        widened.replace("allow: [docker, staging]", "allow: [docker, staging, performance]"),
        encoding="utf-8",
    )
    _git(repo, "commit", "-qam", "widen")
    _git(repo, "checkout", "-q", "main")
    window.activate_action("win.refresh", None)
    pump(0.5)

    window.activate_action("win.refs", None)
    pump(0.6)
    picker = _dialog(window)
    check("the ref picker lists what can be checked out", picker is not None)
    if picker is not None:
        listed = titles(picker)
        check("both branches are there", "main" in listed and "wider" in listed)
        check("and it says a ref carries its own allow list", has_text(picker, "may be launched"))
        snapshot(window, shots / "20-refs.png")
        picker.close()
        pump(0.3)

    window.activate_action("win.clone", None)
    pump(0.6)
    cloner = _dialog(window)
    check("the clone dialog opened", cloner is not None)
    if cloner is not None:
        cloner._url.set_text("ext::sh")
        pump(0.2)
        cloner._go()
        pump(0.4)
        check(
            "a transport that can name a command is refused before git sees it",
            cloner._notice.get_revealed() and "https" in cloner._notice.get_title(),
        )
        check("and it says it never asks for a password", has_text(cloner, "never asks"))
        snapshot(window, shots / "21-clone.png")
        cloner.close()
        pump(0.3)

    # --- the estate view, which is the only one that needs a network ---

    from ordane.insight import stores as stores_module

    check(
        "the estate view is always offered, configured or not",
        window._stack.get_page(window._estate).get_visible(),
    )
    check(
        "and before anything is asked it does not pretend to be loading",
        not window._estate._loading and has_text(window._estate, "nothing has been asked"),
    )

    # Written the way a person writes it, not injected: the settings file is
    # how this gets configured, and visiting the page is what reads it.
    settings = stores_module.settings_path()
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        "ORDANE_INFLUX_URL=http://127.0.0.1:1\n"
        "ORDANE_INFLUX_TOKEN=x\n"
        "ORDANE_NEO4J_URL=http://127.0.0.1:1\n"
        "ORDANE_NEO4J_PASSWORD=x\n",
        encoding="utf-8",
    )
    check("a settings file written after the window opened is read", stores_module.configured().any)

    # The switcher changes the stack directly rather than going through the
    # window's own method, and the estate used to be asked only from that
    # method, so clicking the tab left it spinning for ever.
    window._stack.set_visible_child_name("estate")
    pump(0.4)
    check(
        "changing the page asks the stores, however the page was changed",
        window._estate._loading or bool(window._estate._results),
    )
    until(lambda: not window._estate._loading, 20.0)
    pump(0.4)
    window._stack.set_visible_child_name("dashboard")
    pump(0.3)

    settings.unlink()
    window._estate.refresh(stores_module.Stores())
    pump(0.6)
    check(
        "and it names the file to write rather than sitting empty",
        has_text(window._estate, "stores.env"),
    )
    check(
        "with the template to put in it",
        has_text(window._estate, "copy the template"),
    )
    unreachable = stores_module.Stores(
        influx_url="http://127.0.0.1:1",
        influx_token="x",
        neo4j_url="http://127.0.0.1:1",
        neo4j_password="x",
    )
    window._estate.refresh(unreachable, force=True)
    until(lambda: not window._estate._loading, 20.0)
    pump(0.5)
    check(
        "a store that cannot be reached is reported panel by panel",
        has_text(window._estate, "could not be answered"),
    )
    check("and the rest of the console is untouched", window._catalog is not None)

    # Asking again used to blank the page and spin, which is how a slow store
    # took the whole view away from a reader who already had an answer.
    window._estate.refresh(unreachable, force=True)
    pump(0.2)
    check(
        "asking again keeps the last answer on screen rather than blanking it",
        has_text(window._estate, "could not be answered"),
    )
    until(lambda: not window._estate._loading, 20.0)
    pump(0.4)
    snapshot(window, shots / "18-estate.png")

    # --- the dataset, in the shapes another store reads ---

    window.activate_action("win.export", None)
    pump(0.8)
    exporter = _dialog(window)
    check("the export dialog opened", exporter is not None)
    if exporter is not None:
        check("it says what the file will contain", has_text(exporter, "finished run"))
        snapshot(window, shots / "17-export.png")
        for index, kind in enumerate(export.FORMATS):
            exporter._format.set_selected(index)
            pump(0.1)
            rendered = export.render(exporter._chosen_runs(), kind)
            check(f"`{kind}` renders", isinstance(rendered, str))
        exporter.close()
        pump(0.3)

    # --- objectives, which could only be typed by hand before ---

    window.activate_action("win.objectives", None)
    pump(0.8)
    editor = _dialog(window)
    check("the objectives editor opened", editor is not None)
    if editor is not None:
        check("it lists the ones already declared", len(editor._rows) == 3)
        check(
            "and says what an unmeasurable one would take",
            has_text(editor, "setup needed") or has_text(editor, "what it would take"),
        )
        snapshot(window, shots / "15-objectives.png")
        row = editor._rows[0]
        row._label.set_text("Cutover succeeds, renamed here")
        editor._add({})
        editor._rows[-1]._label.set_text("Written from the window")
        editor._on_save(None)
        pump(1.0)
    written = (repo / ".ordane.yml").read_text()
    check("saving writes them into the configuration", "Written from the window" in written)
    check("and leaves the rest of the file alone", "# What `make help` cannot say." in written)
    check(
        "the console reads them back",
        any("Written from the window" == str(s.get("label")) for s in window._config.slos),
    )

    # --- the checkup, which is the answer to "why does nothing work" ---

    # --- pointing at the shared stores, which used to be a clipboard and a folder ---

    window.activate_action("win.stores", None)
    pump(0.8)
    setup = _dialog(window)
    check("the stores dialog opened", setup is not None)
    if setup is not None:
        check("it asks for both stores", has_text(setup, "InfluxDB") and has_text(setup, "Neo4j"))
        check(
            "and says where it writes them, and who can read it",
            has_text(setup, "only this account can read"),
        )
        # Never saved here: this would write the real settings file.
        check(
            "the secrets are password rows",
            all(
                isinstance(setup._rows[key], Adw.PasswordEntryRow)
                for key in setup._rows
                if key.endswith(("_TOKEN", "_PASSWORD"))
            ),
        )
        # Let the dialog finish animating in: a snapshot mid-transition
        # photographs a half-drawn window and says nothing about the design.
        pump(0.8)
        snapshot(window, shots / "27-stores.png")
        setup.close()
        pump(0.4)

    window.activate_action("win.checkup", None)
    pump(0.8)
    report = _dialog(window)
    check("the checkup opened", report is not None)
    if report is not None:
        check("it says the demo is in good shape", has_text(report, "good shape"))
        snapshot(window, shots / "10-checkup.png")
        report.close()
        pump(0.3)

    # --- the read-only path, which is what a fresh control plane looks like ---

    edit.write(repo, [])
    window.activate_action("win.refresh", None)
    pump(1.2)
    window.activate_action("win.page", GLib.Variant.new_string("actions"))
    pump(0.6)
    check(
        "read-only says nothing can be launched",
        has_text(page(window), "Nothing can be launched"),
    )
    check("and offers the way out", has_text(page(window), "Manage environments"))
    snapshot(window, shots / "08-read-only.png")

    window.activate_action("win.environments", None)
    pump(0.8)
    chooser = _dialog(window)
    check("the environments dialog opened", chooser is not None)
    if chooser is not None:
        check("it lists what `make help` found", "docker" in titles(chooser))
        snapshot(window, shots / "09-environments.png")
        # An environment nothing on disk announced, added by hand.
        chooser._new.set_text("bare-metal")
        chooser._on_add()
        check("an environment can be added by name", "bare-metal" in chooser._switches)
        chooser._new.set_text("not a name!")
        chooser._on_add()
        check(
            "and a name the console will not write is refused",
            chooser._error.get_revealed() and "not a name" not in chooser._switches,
        )
        # An environment whose hosts EC2 decides. Nothing here reaches AWS:
        # what is written is the configuration Ansible's own plugin reads.
        chooser._build_from_aws()
        pump(1.2)
        cloud = _dialog(window)
        check("the EC2 dialog opened", cloud is not None)
        if cloud is not None:
            check(
                "it says no credential is written",
                has_text(cloud, "None is written here"),
            )
            check(
                "it previews the file before writing it",
                "plugin: amazon.aws.aws_ec2" in cloud._preview.get_text(),
            )
            cloud._name.set_text("fleet")
            cloud._regions.set_text("us-east-1, eu-west-2")
            cloud._group_by.set_text("Role")
            pump(0.3)
            check(
                "the preview follows what was typed",
                "eu-west-2" in cloud._preview.get_text()
                and "tags.Role" in cloud._preview.get_text(),
            )
            cloud._regions.set_text("not-a-region")
            pump(0.3)
            check(
                "and a region that is not one refuses to be written",
                not cloud._write.get_sensitive(),
            )
            cloud._regions.set_text("us-east-1")
            pump(0.3)
            snapshot(window, shots / "28-ec2.png")
            cloud._on_write()
            pump(0.5)
            written = repo / "inventory" / "fleet" / "aws_ec2.yml"
            check("it wrote the plugin config", written.is_file())
            check(
                "and the environment joined the list",
                "fleet" in chooser._switches and chooser._switches["fleet"].get_active(),
            )

        chooser._switches["docker"].set_active(True)
        chooser._switches["staging"].set_active(True)
        chooser._on_save(None)
        pump(1.2)
        check(
            "the added one is declared in the file, not only allowed",
            "bare-metal" in (repo / ".ordane.yml").read_text(),
        )
        check(
            "and the console reads it back",
            "bare-metal" in [e.name for e in window._catalog.environments],
        )
    check(
        "saving it makes the console launchable again",
        bool(window._catalog.launchable_environments),
    )
    check(
        "and the comments in the config file survived the edit",
        "# What `make help` cannot say." in (repo / ".ordane.yml").read_text(),
    )

    # --- a repository that cannot be read, which is the last dead end ---

    # The Makefile goes: the repository is still drivable, by ansible-playbook
    # over the playbooks that were always there.
    (repo / "Makefile").rename(repo / "Makefile.hidden")
    window.activate_action("win.refresh", None)
    pump(1.2)
    check(
        "losing the Makefile falls back to driving ansible directly",
        window._catalog is not None and window._catalog.discovery.driver == "ansible",
    )
    check(
        "and the targets are the playbooks",
        any(t.source.endswith(".yml") for t in window._catalog.targets),
    )
    snapshot(window, shots / "14-ansible-driver.png")

    # Now there is nothing left to read at all.
    read_at = window._loaded_at
    (repo / "actions").rename(repo / "actions.hidden")
    window.activate_action("win.refresh", None)
    pump(1.2)
    check("a repository that stops being readable says so", has_text(window, "cannot be re-read"))
    check("and the reading is not restamped as current", window._loaded_at == read_at)
    check("while the views keep what was true a minute ago", "deploy" in titles(page(window)))
    snapshot(window, shots / "11-stale.png")

    # It was never readable at all: there is nothing to keep, so the views go.
    window._catalog = None
    window._catalog_error = "`make help` failed in this repository"
    window._render()
    pump(0.6)
    check(
        "a repository that never read shows a page instead of empty views",
        has_text(page(window), "cannot be read"),
    )
    check("and offers the check rather than nothing", has_text(page(window), "Check this"))
    snapshot(window, shots / "12-unreadable.png")

    (repo / "Makefile.hidden").rename(repo / "Makefile")
    (repo / "actions.hidden").rename(repo / "actions")
    window.activate_action("win.refresh", None)
    pump(1.2)
    check("and recovers when the repository comes back", bool(window._catalog.targets))
    check("back on make", window._catalog.discovery.driver == "make")
    check("with the notice gone", not has_text(window, "cannot be re-read"))

    # --- the ranking, against the catalogue it will actually meet ---

    ranked = search.rank(catalog.targets, "deploy")
    check("`deploy` outranks `activate`", ranked[0].target.name == "deploy")


def _with_class(widget: Gtk.Widget, name: str) -> Gtk.Widget | None:
    """The first widget below this one carrying a CSS class, or None."""
    child = widget.get_first_child()
    while child is not None:
        if child.has_css_class(name):
            return child
        found = _with_class(child, name)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=repo, check=False, capture_output=True)


def _dialog(window) -> Adw.Dialog | None:
    return window.get_visible_dialog() if hasattr(window, "get_visible_dialog") else None


def watch_for_warnings() -> None:
    GLib.log_set_writer_func(_listen, None)


def main() -> int:
    source = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else DEFAULT_REPO
    shots = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else ROOT / "docs" / "images"
    shots.mkdir(parents=True, exist_ok=True)
    watch_for_warnings()

    # The run edits the allow list and records runs, so it works on a copy in a
    # temporary directory: driving the console must never leave the person who
    # ran it with a changed control plane.
    workspace = Path(tempfile.mkdtemp(prefix="ordane-smoke-"))
    repo = workspace / source.name
    shutil.copytree(source, repo)
    state = workspace / "state"

    settings = Settings(repo=repo, state_dir=state, events_path=state / "deployments.jsonl")
    app = ConsoleApplication(settings)

    def run(application) -> bool:
        try:
            drive(application, repo, shots)
        except Exception:  # noqa: BLE001, a crash here is a failure, not a traceback to lose
            traceback.print_exc()
            failures.append("the run raised")
        application.quit()
        return False

    app.connect("activate", lambda application: GLib.idle_add(run, application))

    def give_up() -> bool:
        failures.append("timed out")
        app.quit()
        return False

    GLib.timeout_add_seconds(DEADLINE_SECONDS, give_up)
    app.run([])
    shutil.rmtree(workspace, ignore_errors=True)

    # The one check nobody can forget to write, because everything raises it.
    kinds = sorted({one.split(":")[0].strip() for one in complaints})
    check(
        f"the window drew itself without complaining ({len(complaints)} raised)",
        not complaints,
    )
    for kind in kinds[:5]:
        print(f"      {kind}")

    print()
    if skipped:
        print(f"{len(skipped)} skipped for want of something this machine has not got:")
        for one in skipped:
            print(f"  {one}")
        print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        return len(failures)
    print("every check that could run passed" if skipped else "every check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
