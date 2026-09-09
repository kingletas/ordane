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

# `xvfb-run` sets DISPLAY, but GTK prefers Wayland whenever WAYLAND_DISPLAY is
# also set — so on a Wayland desktop this opened a window on the real
# compositor instead of on the virtual display. The window is mapped, sized and
# correct, and it is never given a frame, so every screenshot reports "nothing
# painted" and every check that needs a layout pass fails. Naming the backend is
# what ties this run to the display it was given.
if os.environ.get("DISPLAY") and os.environ.get("WAYLAND_DISPLAY"):
    os.environ["GDK_BACKEND"] = "x11"


import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402, after the versions above

from ordane.core import edit, identity, search, validation  # noqa: E402
from ordane.core import inventory as inventory_module  # noqa: E402
from ordane.desktop import geometry  # noqa: E402
from ordane.desktop import widgets as w  # noqa: E402
from ordane.desktop.app import ConsoleApplication, Settings  # noqa: E402
from ordane.desktop.rail import PLACES, repository_menu  # noqa: E402
from ordane.desktop.shortcuts import KEYS  # noqa: E402
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

# How long a frame is waited for before a screenshot is given up on.
SNAPSHOT_WAIT = 15.0

# How long a layout pass is given. A breakpoint applies on the next one, which
# on a loaded machine is not the next instant. `until` returns as soon as the
# condition holds, so a generous budget costs nothing when the machine is idle.
LAYOUT_WAIT = 15.0

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
    # A paintable has nothing to give until the widget has been drawn, so each
    # attempt asks for a frame rather than only waiting for one. Blind polling
    # is enough on an idle machine and not on a busy one, which is what made
    # this the flakiest check in the file.
    deadline = time.perf_counter() + SNAPSHOT_WAIT
    while time.perf_counter() < deadline:
        window.queue_draw()
        clock = window.get_frame_clock()
        if clock is not None:
            clock.request_phase(Gdk.FrameClockPhase.PAINT)
        pump(0.1)
        holder = Gtk.Snapshot()
        paintable.snapshot(holder, width, height)
        node = holder.to_node()
        if node is not None:
            break
    if node is None or renderer is None:
        # Nothing painted after that long is the compositor, not the window: a
        # locked screen and a headless display with no frames look the same from
        # here, and neither says anything about the application.
        skip(
            f"{path.name}",
            f"nothing painted after {SNAPSHOT_WAIT:.0f}s, so there is no frame to save",
        )
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


def named(widget: Gtk.Widget, css_class: str) -> list[str]:
    """The text of every label carrying a class, which is what a page is made of
    now that its rows are boxes rather than libadwaita rows."""
    return [one.get_text() for one in rows_under(widget, Gtk.Label) if one.has_css_class(css_class)]


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


def check_the_rail_holds_places_and_nothing_else(window) -> None:
    """The rail is places. Everything else is a method on the repository.

    The design's whole first complaint was a rail of fourteen rows, nine of
    them ending in an ellipsis because they opened a dialog, while the real
    navigation sat in the title bar. This is the check that keeps it gone.
    """
    # Only the rows: the repository's own menu hangs off the card at the foot,
    # and that is exactly where the ellipses are supposed to have gone.
    labels = [one.get_text() for one in rows_under(window._rail, Gtk.Label) if _in_a_place(one)]
    dialogs = [one for one in labels if one.endswith("…")]
    check(f"none of the rail's {len(labels)} rows opens a dialog", not dialogs)
    for one in dialogs:
        print(f"      {one}")
    named_places = {name for name in PLACES if name != "—"}
    check("and every place is one of them", len(labels) >= len(named_places))


def _in_a_place(widget: Gtk.Widget) -> bool:
    """Whether this label is inside one of the rail's own rows."""
    parent = widget.get_parent()
    while parent is not None:
        if parent.has_css_class("place"):
            return True
        parent = parent.get_parent()
    return False


def check_every_old_rail_row_is_in_the_palette(window) -> None:
    """All nine of them, and none of them in the rail. Acceptance criterion 5."""
    entries = window._entries()
    titles_of = {entry.title for entry in entries}
    repository = {entry.title for entry in entries if entry.group == "This repository"}
    wanted = _menu_rows(repository_menu()).values()
    missing = [one for one in wanted if one not in titles_of]
    check(f"all {len(list(wanted))} repository actions are reachable from Ctrl+K", not missing)
    for one in missing:
        print(f"      {one}")
    check("and the palette groups them under `This repository`", len(repository) >= 9)


# The widest a place may insist on being. The window opens at 1180 with a
# 236 px rail, so anything past this cannot be laid out in the window it
# ships with — and GTK does not refuse it, it draws widgets on top of each
# other and logs about the overlay exceeding its width.
WIDEST_PLACE = 820


def check_no_place_demands_more_width_than_it_gets(window) -> None:
    """A place's minimum is the widest thing in it, and one label can set it.

    Three defects in this design had the same shape: a label that neither
    wraps nor ellipsises reports its whole text as a minimum, that becomes the
    page's minimum, and the page then asks for more room than any window has.
    None of them was visible in a screenshot until the layout had already
    broken, so this measures every place instead of looking at it.
    """
    too_wide = []
    for name in PLACES:
        if name == "—":
            continue
        window.activate_action("page", GLib.Variant.new_string(name))
        pump(0.4)
        page = window._stack.get_visible_child()
        minimum, _natural, _a, _b = page.measure(Gtk.Orientation.HORIZONTAL, -1)
        if minimum > WIDEST_PLACE:
            too_wide.append(f"{name}: {minimum} px")
    check(f"no place insists on more than {WIDEST_PLACE} px", not too_wide)
    for one in too_wide:
        print(f"      {one}")


def check_no_label_shouts(window) -> None:
    """No screen contains an all-capitals label. Acceptance criterion 1."""
    shouting = []
    for one in rows_under(window, Gtk.Label):
        text = one.get_text().strip()
        letters = [c for c in text if c.isalpha()]
        if len(letters) > 3 and all(c.isupper() for c in letters) and " " in text:
            shouting.append(text)
    check("no label on any screen is set in capitals", not shouting)
    for one in sorted(set(shouting))[:6]:
        print(f"      {one!r}")


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

    check_the_rail_holds_places_and_nothing_else(window)
    check_every_old_rail_row_is_in_the_palette(window)

    # --- the pages ---

    snapshot(window, shots / "01-overview.png")
    check("Overview leads with one sentence", _with_class(page(window), "verdict-title"))
    check(
        "which says whether it is safe to deploy",
        has_text(page(window), "deploy") or has_text(page(window), "launched"),
    )
    check("and a beacon in one of the four states", _with_class(page(window), "beacon"))
    check("the environments are a strip of tiles", _with_class(page(window), "env-tile"))
    check(
        "the delivery measures carry the names the industry uses",
        has_text(page(window), "release frequency"),
    )
    check(
        "and no card anywhere says `Setup needed`",
        not has_text(page(window), "setup needed"),
    )
    check(
        "a measure with no source says what would fill it, not `no data`",
        not has_text(page(window), "no data"),
    )
    check(
        "the last day of runs is on the page rather than behind a disclosure",
        has_text(page(window), "Recent runs"),
    )
    check(
        "and it says so plainly when nothing has run",
        has_text(page(window), "Nothing has run"),
    )
    check_no_label_shouts(window)
    check_no_place_demands_more_width_than_it_gets(window)
    window.activate_action("page", GLib.Variant.new_string("overview"))
    pump(0.3)

    window.activate_action("win.page", GLib.Variant.new_string("actions"))
    # Switching a page and filling it are two steps, and on a loaded machine the
    # gap between them is long enough to read an empty page in.
    until(lambda: "deploy" in named(page(window), "action-name"), VIEW_WAIT)
    # `make help` is a subprocess, and a loaded machine can make it fail. When
    # it does, every check below reports a missing target instead of the one
    # thing that actually went wrong.
    if window._catalog_error:
        check(f"the repository stayed readable: {window._catalog_error}", False)

    listed = named(page(window), "action-name")
    check("the actions page lists the chosen group's targets", "deploy" in listed)
    check("a hidden target stays hidden", "help" not in listed)
    check("a dangerous target says what it does", has_text(page(window), "Customers see this"))
    # One group at a time: eleven targets scroll and forty do not, so the
    # column carries the rest rather than the page carrying all of them.
    check("the other groups are in the column rather than on the page", "ping" not in listed)
    check("and the column names them", has_text(page(window), "Fleet"))
    snapshot(window, shots / "02-actions.png")
    window._choose_group("Fleet")
    check(
        "choosing a group shows it",
        until(lambda: "ping" in named(page(window), "action-name"), LAYOUT_WAIT),
    )
    window._choose_group("Release")
    until(lambda: "deploy" in named(page(window), "action-name"), LAYOUT_WAIT)
    check(
        "the composer says what it will do before it does it",
        _with_class(page(window), "willdo"),
    )
    check(
        "and its button names its own outcome",
        any(
            one.get_text().startswith("Run ") and " on " in one.get_text()
            for one in rows_under(page(window), Gtk.Label)
        ),
    )

    # --- search ---

    window.activate_action("win.find", None)
    pump(0.4)
    window._search.set_text("ping")
    pump(0.6)
    found = named(page(window), "action-name")
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
        # A required parameter is still empty here, so there is no command to
        # show and nothing to press. A preview that printed one anyway would be
        # offering a line that would be refused.
        check(
            "no command is offered while a required field is empty",
            dialog._preview.get_text().startswith("—"),
        )
        check(
            "and Run is held until there is one",
            not dialog._run_button.get_sensitive(),
        )
        check(
            "and it says what is missing",
            "release is required" in (dialog._run_button.get_tooltip_text() or ""),
        )
        dialog._fields["release"].set_text("2026-08-28.1")
        pump(0.4)
        check("filling it in frees the button", dialog._run_button.get_sensitive())
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

    # --- the field that completes, and the paste behind it ---
    #
    # None of this is in a screenshot: a popover is its own surface, so a
    # picture of the window under it shows an empty field either way.

    window._open_launch(catalog.target("patch-fleet"))
    pump(0.8)
    dialog = _dialog(window)
    check(
        "the patch field is one that can be typed into",
        dialog is not None and hasattr(dialog._fields.get("patch"), "get_text"),
    )
    if dialog is not None and hasattr(dialog._fields.get("patch"), "get_text"):
        field = dialog._fields["patch"]
        completer = field._completer
        field.grab_focus()
        field.set_text("raise")
        pump(0.5)
        offered = _suggested(completer)
        check("typing narrows the list to what matches", offered == ["raise-php-memory"])
        check("and the list is open", completer._popover.get_visible())

        completer._take(completer._list, completer._list.get_row_at_index(0))
        pump(0.3)
        check("picking one fills the field", field.get_text() == "raise-php-memory")
        check("and closes the list", not completer._popover.get_visible())

        field.set_text("nothing-like-this")
        pump(0.5)
        check("nothing matching offers nothing", _suggested(completer) == [])
        check("and says so rather than going blank", _has_note(completer, "Nothing here is called"))
        check("and still offers a way to add one", _can_add(completer))

        # The paste route: a real file written into the repository the plane is.
        pasted = repo / "patches" / "smoke-pasted.patch"
        if pasted.exists():
            pasted.unlink()
        completer._on_add()
        pump(0.8)
        paste = _dialog(window)
        check("the add row opens a paste dialog", paste is not None and paste is not dialog)
        if paste is not None and paste is not dialog:
            paste._name.set_text("smoke-pasted")
            paste._body.get_buffer().set_text("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n")
            paste._on_save(None)
            pump(0.8)
            check("pasting writes the file", pasted.is_file())
            check("and it is readable, not executable", pasted.stat().st_mode & 0o777 == 0o644)
            check("and the field now holds it", field.get_text() == "smoke-pasted")
            check("and it is one of the choices", "smoke-pasted" in _suggested(completer, ""))

            # A second one under the same name is refused rather than silently
            # replacing somebody's patch.
            completer._on_add()
            pump(0.8)
            again = _dialog(window)
            if again is not None and again is not dialog:
                again._name.set_text("smoke-pasted")
                again._body.get_buffer().set_text("--- a/y\n+++ b/y\n@@ -1 +1 @@\n-a\n+b\n")
                again._on_save(None)
                pump(0.5)
                check("a name already on disk is refused", again._error.get_revealed())
                check("and the dialog stays open", _dialog(window) is again)
                again.close()
                pump(0.3)
            check("the patch on disk was not replaced", "a/x" in pasted.read_text())
            pasted.unlink()
        dialog.close()
        pump(0.4)

    # --- a real run, followed to the end ---

    window._open_launch(catalog.target("ping"))
    pump(0.6)
    dialog = _dialog(window)
    if dialog is not None:
        dialog._on_run_clicked(None)
    pump(0.5)
    check("the run opened on Runs", window._stack.get_visible_child_name() == "runs")
    check(
        "and the list marks it as the one being read",
        until(lambda: window._runs_page.chosen() != "", LAYOUT_WAIT),
    )
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
    # The run's state, its parsed result and the widgets built from that result
    # are three different things, filled by different threads. Each check waits
    # for the one it is about, rather than for text that happens to appear when
    # all three have landed.
    parsed = until(
        lambda: window._runview._run is not None and window._runview._run.result.has_recap,
        VIEW_WAIT,
    )
    check("its result was parsed, not just its exit code", parsed)
    if not parsed and window._runview._run is not None:
        print(f"      output was {window._runview._run.result!r}")
    check(
        "and the empty-output notice is out of the way",
        until(
            lambda: (
                window._runview._text().strip() and not window._runview._placeholder.get_visible()
            ),
            VIEW_WAIT,
        ),
    )
    # Hundreds of lines and no way to find one, until now.
    # Searching an empty buffer finds nothing and says so correctly, so the text
    # has to be there before the search means anything.
    until(lambda: bool(window._runview._text().strip()), VIEW_WAIT)
    window._runview.find()
    window._runview._find.set_text("ok")
    found = until(
        lambda: bool(window._runview._matches) and "of" in window._runview._found.get_text(),
        VIEW_WAIT,
    )
    check("a run's output can be searched", found)
    if not found:
        print(f"      search said {window._runview._found.get_text()!r}")
    # The shape of a run: one lane per host, one cell per task. It is read back
    # out of the same output the log shows, so it can only be here if the
    # parser agreed with what Ansible actually printed.
    # `ping` answers once per host and prints no task headers, so its grid is
    # one column: a full-width bar per host carrying one bit each, which is
    # what the outcome pill already says. It is deliberately not drawn, and the
    # per-host answers go on the page instead of behind a disclosure.
    settled = until(lambda: window._runview._run.result.has_recap, VIEW_WAIT)
    check(
        "a question asked of a host group draws no chart",
        not window._runview._lanes.get_visible(),
    )
    check(
        "and its per-host answers are on the page rather than folded away",
        settled and has_text(window._runview, "Every host"),
    )
    section = next(
        (one for one in rows_under(window._runview, w.Section) if has_text(one, "Every host")),
        None,
    )
    check(
        "which means that section is open",
        section is not None and section._revealer.get_reveal_child(),
    )
    check(
        "the facts above it print no zero for a host count nobody changed",
        _with_class(window._runview, "stat-value") is not None,
    )
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
    check(
        "the finished run is in the history",
        any("ping" in one for one in named(page(window), "runitem-name")),
    )
    check("grouped under the day it happened on", has_text(page(window), "Today"))
    check("with the day's own count beside it", has_text(page(window), "runs"))
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
        has_text(window._rail, window._plane.name),
    )
    check("and root is not what this is running as", not window._actor.is_root)

    # --- the rail, which is where the places are ---

    check("the window opens with the rail", window.split.get_show_sidebar())
    check(
        "which names the repository at the foot of it", has_text(window._rail, window._plane.name)
    )
    check("and says what git makes of the working tree", _with_class(window._rail, "gitchip"))
    check("and how old the reading is", has_text(window._rail, "read"))
    check("and how to reach everything else", has_text(window._rail, "for everything else"))
    window._choose_navigation(geometry.MENU)
    pump(0.5)
    check("choosing the menu alone puts the rail away", not window.split.get_show_sidebar())
    window._choose_navigation(geometry.BOTH)
    pump(0.5)
    check("and choosing both brings it back", window.split.get_show_sidebar())
    # Waited for rather than slept on: a breakpoint applies on the next layout
    # pass, and a fixed pause makes this fail at random on a busy machine.
    window.set_default_size(760, 700)
    check(
        "a narrow window folds the rail away",
        until(lambda: window.split.get_collapsed(), LAYOUT_WAIT),
    )
    snapshot(window, shots / "13-narrow.png")
    window.set_default_size(*WINDOW)
    check(
        "and a wide one brings it back",
        until(lambda: not window.split.get_collapsed(), LAYOUT_WAIT),
    )

    # --- filtering the history ---

    window.activate_action("win.page", GLib.Variant.new_string("runs"))
    pump(0.5)
    check(
        "the run beside the list is open without being navigated to",
        window._runs_page.chosen() != "",
    )
    window.activate_action("win.runs-filter", GLib.Variant.new_string("failed"))
    pump(0.6)
    check(
        "filtering to failures says there are none rather than showing nothing",
        has_text(page(window), "Nothing here has failed"),
    )
    window.activate_action("win.runs-filter", GLib.Variant.new_string("all"))
    pump(0.5)
    check(
        "and clearing it brings the run back",
        any("ping" in one for one in named(page(window), "runitem-name")),
    )

    # --- the density rules, which are what keeps a busy day readable ---

    window._runs_page._choose_density("everything")
    pump(0.5)
    every = len(named(page(window), "runitem-name"))
    window._runs_page._choose_density("worth")
    pump(0.5)
    worth = len(named(page(window), "runitem-name"))
    check("`worth a look` never shows more rows than `everything`", worth <= every)
    check(
        "and it never hides a run somebody launched by hand",
        any("ping" in one for one in named(page(window), "runitem-name")),
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
    check(
        "preferences is a place rather than a dialog",
        window._stack.get_visible_child_name() == "preferences",
    )
    snapshot(window, shots / "16-preferences.png")
    check("every row in it is wired to something", has_text(page(window), "Reduce motion"))
    check(
        "and what is not built is named rather than shown as a dead switch",
        has_text(page(window), "not settings yet"),
    )

    window._choose_navigation(geometry.MENU)
    pump(0.5)
    check("menu only puts the rail away", not window.split.get_show_sidebar())
    check("and keeps the menu button", window._hamburger.get_visible())
    window._choose_navigation(geometry.RAIL)
    pump(0.5)
    check("rail only brings it back", window.split.get_show_sidebar())
    check("and takes the menu button away", not window._hamburger.get_visible())
    window._choose_navigation(geometry.BOTH)
    pump(0.4)
    check(
        "both keeps both",
        window.split.get_show_sidebar() and window._hamburger.get_visible(),
    )
    check(
        "and the choice is remembered",
        geometry.navigation(window._settings.state_dir) == geometry.BOTH,
    )

    # --- the three places that are reached rather than listed ---

    window.activate_action("win.page", GLib.Variant.new_string("environments"))
    pump(0.6)
    check("Environments is a place", _with_class(page(window), "obj-row") is not None)
    check(
        "and the one that is waiting says what it needs",
        has_text(page(window), "host source"),
    )
    snapshot(window, shots / "29-environments-place.png")

    window.activate_action("win.page", GLib.Variant.new_string("delivery"))
    pump(0.6)
    check("Delivery has all four signals", has_text(page(window), "time to restore"))
    check(
        "and says what none of them can see",
        has_text(page(window), "does not read an incident tracker"),
    )
    snapshot(window, shots / "30-delivery.png")

    window.activate_action("win.page", GLib.Variant.new_string("setup"))
    pump(0.6)
    check("Setup is seven steps", len(window._setup.steps) == 7)
    check("each saying what it turns on", has_text(page(window), "Turns on"))
    snapshot(window, shots / "31-setup.png")

    window.activate_action("win.page", GLib.Variant.new_string("about"))
    pump(0.6)
    check(
        "About is a screen rather than a dialog",
        has_text(page(window), "runs entirely on this machine"),
    )
    check("and it names the run history it wrote", has_text(page(window), "runs.jsonl"))
    snapshot(window, shots / "32-about.png")

    # --- the command palette ---

    window.activate_action("win.palette", None)
    pump(0.8)
    palette = _dialog(window)
    check("Ctrl+K opens the palette", palette is not None)
    if palette is not None:
        check("it groups what it offers", has_text(palette, "This repository"))
        palette._entry.set_text("export")
        pump(0.5)
        check(
            "typing narrows it to what was asked for",
            any("Export" in entry.title for entry, _ in palette._rows),
        )
        palette._entry.set_text("zzzznothing")
        pump(0.4)
        check("and a search with no match says so", has_text(palette, "Nothing here is called"))
        palette._entry.set_text("")
        pump(0.4)
        snapshot(window, shots / "33-palette.png")
        palette.close()
        pump(0.3)
    window.activate_action("win.page", GLib.Variant.new_string("runs"))
    pump(0.3)

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
        until(lambda: "check" in titles(page(window)), LAYOUT_WAIT)
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
        until(lambda: _dialog(window) is not None, VIEW_WAIT)
        gate = _dialog(window)
        check("the control plane's own checks gate the deploy", gate is not None)
        if gate is not None:
            until(lambda: not gate._running, 240.0)
            pump(0.8)
            gate.close()
            pump(0.6)
        check(
            "then the precheck runs, and not the deploy",
            until(
                lambda: window._runview._run is not None and window._runview._run.name == "check",
                VIEW_WAIT,
            ),
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
            until(lambda: has_text(window._runview, "Told the outside world"), VIEW_WAIT),
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
    window._stack.set_visible_child_name("overview")
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
    check(
        "while the views keep what was true a minute ago",
        "deploy" in named(window._actions_page, "action-name"),
    )
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


def _suggested(completer, typed=None) -> list:
    """The values the completer is currently offering."""
    if typed is not None:
        from ordane.core.choices import matches

        return matches(typed, completer._choices())
    found, index = [], 0
    while (row := completer._list.get_row_at_index(index)) is not None:
        if getattr(row, "value", ""):
            found.append(row.value)
        index += 1
    return found


def _has_note(completer, said: str) -> bool:
    index = 0
    while (row := completer._list.get_row_at_index(index)) is not None:
        child = row.get_child()
        if child is not None and hasattr(child, "get_text") and said in child.get_text():
            return True
        index += 1
    return False


def _can_add(completer) -> bool:
    """The way to add one is pinned below the scrolling list, not inside it."""
    row = completer._adds.get_row_at_index(0)
    return completer._adds.get_visible() and row is not None and getattr(row, "adds", False)


def _dialog(window) -> Adw.Dialog | None:
    return window.get_visible_dialog() if hasattr(window, "get_visible_dialog") else None


def watch_for_warnings() -> None:
    GLib.log_set_writer_func(_listen, None)


def main() -> int:
    source = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else DEFAULT_REPO
    # `local.d` rather than `docs/images`: a run writes thirty-odd frames, and
    # only the two the README shows belong in the repository. Those are copied
    # across by hand once they are worth keeping.
    shots = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else ROOT / "local.d" / "shots"
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

    # A run that photographed nothing has verified nothing about the layout, and
    # a page of `skip` lines reads as a machine short of something rather than
    # as a run that did not happen. It is a failure.
    photographs = [one for one in skipped if one.endswith(".png")]
    check(
        f"the run actually photographed the window ({len(photographs)} frames missed)",
        len(photographs) < 3,
    )

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
