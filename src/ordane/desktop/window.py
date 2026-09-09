"""The main window: a rail of places, a stage, and one place that refreshes them.

The rail holds places and nothing else. Everything that is a method on the
repository — re-read it, open its configuration, export its history, check it,
open another — is on the repository card's menu and in the command palette, so
there is one navigation system rather than two half ones.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk, Pango  # noqa: E402

from ..core import adhoc, identity, plane, recent, repository  # noqa: E402
from ..core import catalog as catalog_module  # noqa: E402
from ..core import command as command_module  # noqa: E402
from ..core import config as config_module  # noqa: E402
from ..core import doctor as doctor_module  # noqa: E402
from ..core import inventory as inventory_module  # noqa: E402
from ..core import runbook as runbook_module  # noqa: E402
from ..core import validation as validation_module  # noqa: E402
from ..core.config import CONFIG_NAME  # noqa: E402
from ..insight import (
    density,  # noqa: E402
    metrics,  # noqa: E402
)
from ..insight import environments as env_module  # noqa: E402
from ..insight import health as health_module  # noqa: E402
from ..insight import relaunch as relaunch_module  # noqa: E402
from ..insight import runs as runs_module  # noqa: E402
from ..insight import setup as setup_module  # noqa: E402
from ..insight import stores as stores_module  # noqa: E402
from ..insight import verdict as verdict_module  # noqa: E402
from ..presentation.language import PLANE  # noqa: E402
from ..presentation.text import ago as text_ago  # noqa: E402
from ..presentation.text import plural  # noqa: E402
from ..record import checks as checks_module  # noqa: E402
from ..record import decisions as decisions_module  # noqa: E402
from ..record import runner as runner_module  # noqa: E402
from ..record.runner import Runner, RunnerError  # noqa: E402
from ..record.store import RunStore, new_id  # noqa: E402
from . import aboutpage, availability, geometry, storesetup  # noqa: E402
from . import menu as menu_module  # noqa: E402
from . import widgets as w  # noqa: E402
from .actionspage import ActionsPage  # noqa: E402
from .checks import ChecksDialog  # noqa: E402
from .checkup import CheckupDialog  # noqa: E402
from .dataset import ExportDialog  # noqa: E402
from .deliverypage import DeliveryPage  # noqa: E402
from .environments import EnvironmentsDialog  # noqa: E402
from .environmentspage import EnvironmentsPage  # noqa: E402
from .estate import Estate  # noqa: E402
from .glyphs import Glyph  # noqa: E402
from .launch import LaunchDialog  # noqa: E402
from .objectives import ObjectivesDialog, saved_message  # noqa: E402
from .overview import Overview  # noqa: E402
from .palette import Entry, PaletteDialog  # noqa: E402
from .prefspage import PrefsPage  # noqa: E402
from .rail import Rail, Tallies  # noqa: E402
from .refs import CloneDialog, RefsDialog  # noqa: E402
from .runspage import RunsPage  # noqa: E402
from .runview import RunView  # noqa: E402
from .setuppage import SetupPage  # noqa: E402
from .shortcuts import for_action  # noqa: E402
from .trail import Trail  # noqa: E402

REFRESH_SECONDS = 5

# How often a sequence looks to see whether its current step has ended. Short
# enough that a check and the operation after it feel like one action.
STEP_POLL_MS = 250

# How wide a toast may get, in pixels. It was a character count, which is a
# guess about the font: 56 characters is 1236 px in the font a CI runner
# has and comfortably less here, so the overlay asked for more width than
# the window had and said so, hundreds of times.
TOAST_WIDTH_PX = 420

# X11 and Wayland both number the side buttons this way, and every other
# application on this desktop reads them as back and forward.
MOUSE_BACK = 8
MOUSE_FORWARD = 9

APP_NAME = "Ordane"

OVERVIEW = "overview"
ACTIONS = "actions"
RUNS = "runs"
ENVIRONMENTS = "environments"
ESTATE = "estate"
DELIVERY = "delivery"
SETUP = "setup"
ABOUT = "about"
PREFERENCES = "preferences"

# The places in the rail, and the three screens that are reached from them.
PLACES = (OVERVIEW, ACTIONS, RUNS, ENVIRONMENTS, ESTATE, DELIVERY)
PAGES = (*PLACES, SETUP, ABOUT, PREFERENCES)

TITLES = {
    OVERVIEW: "Overview",
    ACTIONS: "Actions",
    RUNS: "Runs",
    ENVIRONMENTS: "Environments",
    ESTATE: "Estate",
    DELIVERY: "Delivery",
    SETUP: "Setup",
    ABOUT: "About Ordane",
    PREFERENCES: "Preferences",
}

READ_ONLY = "Read-only: no environment has been named yet"

GUIDE_URL = f"{menu_module.PROJECT}/blob/main/docs/user-guide.md"


class ConsoleWindow(Adw.ApplicationWindow):
    """Owns the store, the runner and every place."""

    def __init__(self, application, settings) -> None:
        super().__init__(application=application, title=APP_NAME)
        self.add_css_class("ordane")
        width, height, maximised = geometry.restore(settings.state_dir)
        self.set_default_size(width, height)
        # A breakpoint needs the window to declare how small it may get, and
        # below this the rail and a place cannot both fit.
        self.set_size_request(*geometry.MINIMUM)
        if maximised:
            self.maximize()
        self.connect("close-request", self._on_close)
        self._settings = settings
        self._store = RunStore(settings.state_dir)
        self._store.prepare()
        self._decisions = decisions_module.DecisionStore(settings.state_dir)
        declared = config_module.load_quietly(settings.repo).control_plane
        self._plane = plane.of(settings.repo, declared)
        self._runner = Runner(
            self._store,
            settings.repo,
            settings.events_path,
            plane=self._plane.name,
            lock_scope=config_module.load_quietly(settings.repo).lock_scope,
        )
        self._catalog = None
        self._config = config_module.Config()
        self._catalog_error = ""

        self._loaded_at = 0.0
        self._checkout = repository.Checkout()
        self._runs: list = []
        self._standings: list = []
        self._snapshot = None
        self._setup = None
        self._verdict = None
        self._actions_group = ""
        self._runs_filter = runs_module.ALL
        self._stores = stores_module.configured()
        # What each environment holds, asked once and remembered. It is read
        # off the launch path on purpose: a run must not wait on a cloud API.
        self._inventories: dict[str, inventory_module.Inventory] = {}
        self._sequence: _Sequence | None = None
        self._recovery = ""

        self._actions()
        self._build()
        menu_module.install_accelerators(application)
        self._apply_appearance()
        self._reload()
        if settings.page in PAGES:
            self._go(settings.page)
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._tick)

    # --- what the window can be asked to do ---

    def _actions(self) -> None:
        """One action per thing the menu, the keyboard and a button all reach."""
        page = Gio.SimpleAction.new_stateful(
            "page", GLib.VariantType.new("s"), GLib.Variant.new_string(OVERVIEW)
        )
        page.connect("activate", lambda a, v: self._go(v.get_string()))
        self.add_action(page)
        self._page_action = page

        chosen = Gio.SimpleAction.new_stateful(
            "runs-filter", GLib.VariantType.new("s"), GLib.Variant.new_string(runs_module.ALL)
        )
        chosen.connect("activate", lambda a, v: self._filter_runs(v.get_string()))
        self.add_action(chosen)
        self._filter_action = chosen

        opener = Gio.SimpleAction.new("open-recent", GLib.VariantType.new("s"))
        opener.connect("activate", lambda _a, v: self._open_repository(Path(v.get_string())))
        self.add_action(opener)

        for name, handler in (
            ("back", self._leave),
            ("go-back", self._go_back),
            ("go-forward", self._go_forward),
            ("find", self._focus_search),
            ("palette", self._show_palette),
            ("refresh", self._reload),
            ("configure", self._open_config),
            ("folder", self._open_folder),
            ("environments", self._choose_environments),
            ("checkup", self._show_checkup),
            ("checks", self._show_checks),
            ("rail", self._toggle_rail),
            ("objectives", self._edit_objectives),
            ("export", self._export_dataset),
            ("stores-folder", self._open_stores_folder),
            ("stores", self._choose_stores),
            ("preferences", lambda: self._go(PREFERENCES)),
            ("open", self._open_another),
            ("clone", self._open_from_url),
            ("recover", self._run_recovery),
            ("refs", self._choose_ref),
            ("shortcuts", self._show_shortcuts),
            ("guide", self._open_guide),
            ("about", lambda: self._go(ABOUT)),
            ("close", self.close),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, run=handler: run())
            self.add_action(action)

    # --- layout ---

    def _build(self) -> None:
        self._trail = Trail()
        self._retracing = False

        self._runview = RunView(
            self._cancel_run,
            self._relaunch,
            steps_of=self._store.steps_of,
            on_open=self._open_run,
            notice_task=lambda: self._config.notifications_task,
        )

        self._overview = Overview(
            on_open_run=self._open_run, on_remedy=self._remedy, on_go=self._go
        )
        self._actions_page = ActionsPage(
            on_launch=self._launch_simply,
            on_open_full=self._open_launch,
            on_search=self._choose_group,
        )
        self._runs_page = RunsPage(
            detail=self._runview, on_open=self._open_run, on_relaunch=self._relaunch
        )
        self._environments_page = EnvironmentsPage(
            on_manage=self._choose_environments,
            on_ask=self._ask_hosts,
            on_run_here=lambda _name: self._go(ACTIONS),
        )
        # Its own place, because it is the only one that needs a network. The
        # rest read files on this machine and keep working when nothing is up.
        self._estate = Estate()
        self._estate._on_copied = self._toast
        self._delivery_page = DeliveryPage(on_remedy=self._remedy, on_go=self._go)
        self._setup_page = SetupPage(on_remedy=self._remedy)
        self._about_page = aboutpage.AboutPage(
            on_copy=self._copy_details,
            on_guide=self._open_guide,
            on_shortcuts=self._show_shortcuts,
        )
        self._prefs_page = PrefsPage(
            state_dir=self._settings.state_dir,
            on_theme=self._choose_theme,
            on_density=self._choose_density,
            on_switch=self._flip_switch,
            on_navigation=self._choose_navigation,
        )

        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE)
        self._stack.add_css_class("stage")
        self._stack.add_named(self._overview, OVERVIEW)
        # Actions scrolls as one page; Runs does not, because each of its two
        # panes scrolls on its own and an outer scroller would fight them.
        self._stack.add_named(w.scrolled(_well(self._actions_page)), ACTIONS)
        self._stack.add_named(_well(self._runs_page), RUNS)
        self._stack.add_named(self._environments_page, ENVIRONMENTS)
        self._stack.add_named(self._estate, ESTATE)
        self._stack.add_named(self._delivery_page, DELIVERY)
        self._stack.add_named(self._setup_page, SETUP)
        self._stack.add_named(self._about_page, ABOUT)
        self._stack.add_named(self._prefs_page, PREFERENCES)
        self._stack.connect("notify::visible-child-name", self._on_page_changed)

        # A repository that cannot be read is shown in place of the places
        # rather than behind a notice over six empty ones.
        self._broken = w.box(spacing=16)
        self._surface = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE)
        self._surface.add_named(self._stack, "console")
        self._surface.add_named(self._broken, "broken")
        self._surface.set_hexpand(True)

        self._rail = Rail(self._go)
        self._navigation = geometry.navigation(self._settings.state_dir)

        self.split = Adw.OverlaySplitView(sidebar=self._rail, max_sidebar_width=280)
        self.split.set_min_sidebar_width(236)

        # The top bar belongs to the stage, not to the window: the rail is an
        # instrument body running the whole height beside it, which is the
        # thing that stops the two reading as one striped surface.
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(self._top_bar())
        toolbar.add_top_bar(self._search_bar)
        toolbar.add_top_bar(self._root_banner())
        self._notice = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        toolbar.add_top_bar(self._notice)
        toolbar.set_content(self._surface)
        self.split.set_content(toolbar)

        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(self.split)
        self.set_content(self._toasts)
        self.add_breakpoint(breakpoint_for(self))

        # Claimed on the capture phase so a row underneath cannot swallow it,
        # and on button 0 because GTK names only the first three.
        buttons = Gtk.GestureClick(button=0, propagation_phase=Gtk.PropagationPhase.CAPTURE)
        buttons.connect("pressed", self._on_mouse_button)
        self.add_controller(buttons)
        self.connect("notify::is-active", self._on_focus)
        self._apply_navigation()

    def _top_bar(self) -> Gtk.Widget:
        """The place you are in, what it is about, and the four things beside it."""
        header = Adw.HeaderBar()
        header.add_css_class("topbar")
        header.set_title_widget(Gtk.Box())

        crumb = w.row(8)
        self._crumb = w.label("Overview", "crumb")
        crumb.append(self._crumb)
        self._crumb_sub = w.label("", "crumb-sub")
        crumb.append(self._crumb_sub)

        self._rail_button = Gtk.ToggleButton(
            icon_name="sidebar-show-symbolic", tooltip_text="Show or hide the rail (Ctrl+B)"
        )
        self._rail_button.add_css_class("iconbtn")
        self._rail_button.connect("toggled", self._rail_toggled)
        header.pack_start(self._rail_button)
        header.pack_start(crumb)

        self._hamburger = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            menu_model=menu_module.primary_menu(self._others()),
            tooltip_text="Main menu",
        )
        self._hamburger.add_css_class("iconbtn")
        header.pack_end(self._hamburger)
        header.pack_end(
            w.icon_button(
                "view-refresh-symbolic",
                "Re-read the repository (Ctrl+R)",
                action="win.refresh",
            )
        )
        header.pack_end(self._search_button())

        # The action search still has a bar of its own: it is how a control
        # plane with thirty-five actions is used at all.
        self._search = Gtk.SearchEntry(placeholder_text="Find an action")
        self._search.connect("search-changed", lambda *_: self._render_actions())
        self._search_bar = Gtk.SearchBar(child=self._search)
        self._search_bar.connect_entry(self._search)
        self._search_bar.set_search_mode(False)
        return header

    def _search_button(self) -> Gtk.Widget:
        """The command surface, said out loud rather than left to be discovered."""
        line = w.row(8)
        line.append(Glyph("search", 13))
        line.append(w.label("Search or run a command"))
        line.append(w.spacer())
        keys = w.row(3)
        keys.append(w.keycap("Ctrl"))
        keys.append(w.keycap("K"))
        line.append(keys)
        button = Gtk.Button(child=line, valign=Gtk.Align.CENTER)
        button.add_css_class("searchbtn")
        button.set_size_request(220, -1)
        button.set_tooltip_text("Everything this console can do")
        button.set_action_name("win.palette")
        return button

    def _root_banner(self) -> Gtk.Widget:
        # Running as root is a standing fact about the whole session, so it is
        # not the notice: that one comes and goes with the repository.
        self._actor = identity.who()
        banner = Adw.Banner(
            title=f"Running as root: {self._actor.summary}. {identity.ROOT_WARNING}",
            revealed=self._actor.is_root,
        )
        banner.add_css_class("error")
        return banner

    # --- appearance ---

    def _apply_appearance(self) -> None:
        self._choose_theme(geometry.theme(self._settings.state_dir))
        self._choose_density(geometry.density(self._settings.state_dir))

    def _choose_theme(self, chosen: str) -> None:
        Adw.StyleManager.get_default().set_color_scheme(
            {
                geometry.LIGHT: Adw.ColorScheme.FORCE_LIGHT,
                geometry.DARK: Adw.ColorScheme.FORCE_DARK,
            }.get(chosen, Adw.ColorScheme.DEFAULT)
        )

    def _choose_density(self, chosen: str) -> None:
        if chosen == geometry.COMPACT:
            self.add_css_class("compact")
        else:
            self.remove_css_class("compact")

    def _flip_switch(self, key: str, _on: bool) -> None:
        """Applied as it is set: a preference that waits for a restart is a note."""
        if key == "reduce-motion":
            self._overview._signature = None
            self._render(reread_catalog=False)

    def _on_focus(self, *_args) -> None:
        """Picks up commits made in an editor, when that is what was asked for."""
        if not self.is_active():
            return
        if not geometry.switch(self._settings.state_dir, "reread-on-focus"):
            return
        if self._loaded_at and time.monotonic() - self._loaded_at < REFRESH_SECONDS:
            return
        self._reload()

    # --- moving between places ---

    def _go(self, name: str) -> None:
        if name in PAGES:
            self._stack.set_visible_child_name(name)

    def _on_page_changed(self, *_args) -> None:
        """However the place changed: a key, an action, or the rail clicked."""
        name = self._stack.get_visible_child_name()
        if not self._retracing and name:
            self._trail.visit(name)
        if name in PAGES:
            self._page_action.set_state(GLib.Variant.new_string(name))
        self._rail.set_current(name if name in PLACES else "")
        self._show_crumb(name)
        if name == ESTATE:
            # Re-read: the settings file may have been written since the window
            # opened, which is the commonest way this gets configured.
            self._stores = stores_module.configured()
            self._estate.refresh(self._stores)
        elif name == PREFERENCES:
            self._prefs_page.render()
        elif name == ABOUT:
            self._render_about()

    def _show_crumb(self, name: str | None) -> None:
        self._crumb.set_text(TITLES.get(name or "", APP_NAME))
        said = self._context(name or "")
        # With the rail away there is nothing else on screen naming the
        # repository this window drives, and that is the one fact a person
        # must never have to go and look for.
        if not self.split.get_show_sidebar() and self._plane.name not in said:
            said = f"{self._plane.name} · {said}" if said else self._plane.name
        self._crumb_sub.set_text(said)

    def _context(self, name: str) -> str:
        """One phrase under the place name, and it is about this repository."""
        catalog = self._catalog
        if name == ACTIONS and catalog is not None:
            return f"{plural(len(catalog.targets), 'action')} defined here"
        if name == RUNS:
            return f"{plural(len(self._runs), 'run')} recorded"
        if name == ENVIRONMENTS and catalog is not None:
            return f"{len(catalog.launchable_environments)} of {len(catalog.environments)} ready"
        if name == ESTATE:
            return "what the shared stores know"
        if name == DELIVERY:
            return ", ".join(self._config.metric_environments) or "every environment"
        if name == SETUP and self._setup is not None:
            return self._setup.progress_text
        return self._plane.name

    def _retrace(self, page: str | None) -> None:
        """Steps to a place without recording the step as somewhere new."""
        if page is None:
            return
        self._retracing = True
        try:
            self._go(page)
        finally:
            self._retracing = False

    def _go_back(self) -> None:
        self._retrace(self._trail.back())

    def _go_forward(self) -> None:
        self._retrace(self._trail.forward())

    def _on_mouse_button(self, gesture, _n_press: int, _x: float, _y: float) -> None:
        """Buttons 8 and 9 are back and forward on every mouse that has them."""
        button = gesture.get_current_button()
        if button == MOUSE_BACK:
            self._go_back()
        elif button == MOUSE_FORWARD:
            self._go_forward()

    def _focus_search(self) -> None:
        # On a run, the thing worth finding is a line of its output.
        if self._stack.get_visible_child_name() == RUNS:
            self._runview.find()
            return
        self._go(ACTIONS)
        self._search_bar.set_search_mode(True)
        self._search.grab_focus()

    def _leave(self) -> None:
        if self._search.get_text():
            self._search.set_text("")
        elif self._search_bar.get_search_mode():
            self._search_bar.set_search_mode(False)

    def _toggle_rail(self) -> None:
        self.split.set_show_sidebar(not self.split.get_show_sidebar())
        self._rail_button.set_active(self.split.get_show_sidebar())

    def _rail_toggled(self, button) -> None:
        self.split.set_show_sidebar(button.get_active())
        self._show_crumb(self._stack.get_visible_child_name())

    def _apply_navigation(self) -> None:
        """The rail, the menu, or both: whichever this person keeps.

        The menu is never taken away on a narrow window: the rail folds there,
        and hiding both would leave every place with nowhere to be reached.
        """
        keeps_rail = self._navigation in (geometry.RAIL, geometry.BOTH)
        self.split.set_show_sidebar(keeps_rail)
        self._rail_button.set_active(keeps_rail)
        self._hamburger.set_visible(
            self._navigation in (geometry.MENU, geometry.BOTH) or not keeps_rail
        )
        self._show_crumb(self._stack.get_visible_child_name())

    def _choose_navigation(self, chosen: str) -> None:
        self._navigation = chosen
        geometry.save_navigation(self._settings.state_dir, chosen)
        self._apply_navigation()

    # --- the command palette ---

    def _show_palette(self) -> None:
        PaletteDialog(self._entries(), lambda entry: entry.run()).present(self)

    def _entries(self) -> list[Entry]:
        """Everything reachable, grouped the way a person asks for it.

        All nine of the entries the rail used to carry are in `This repository`,
        and none of them is in the rail.
        """
        found: list[Entry] = []
        catalog = self._catalog
        if catalog is not None:
            for target in catalog.targets:
                for environment in catalog.launchable_environments:
                    if target.fixed_environment and environment.name != target.fixed_environment:
                        continue
                    found.append(
                        Entry(
                            group="Run",
                            title=f"Run {target.name} on {environment.name}",
                            run=lambda t=target, e=environment.name: self._launch_simply(
                                t.name, e, False
                            ),
                            glyph="actions",
                            terms=target.description,
                        )
                    )

        for title, action, icon, terms in (
            ("Re-read the repository", "win.refresh", "view-refresh-symbolic", "reload again"),
            (
                f"Open {CONFIG_NAME}",
                "win.configure",
                "text-x-generic-symbolic",
                "config configuration edit",
            ),
            ("Show the repository folder", "win.folder", "folder-symbolic", "files directory"),
            (
                "Choose what runs…",
                "win.refs",
                "media-playlist-repeat-symbolic",
                "ref branch tag checkout",
            ),
            (
                "Manage environments…",
                "win.environments",
                "preferences-system-symbolic",
                "allow production read-only",
            ),
            ("Set up objectives…", "win.objectives", "starred-symbolic", "slo target"),
            (
                "Run this repository's own checks…",
                "win.checks",
                "object-select-symbolic",
                "validate suite tests",
            ),
            (
                "Check that this repository is set up correctly",
                "win.checkup",
                "emblem-important-symbolic",
                "doctor diagnose what is wrong setup",
            ),
            ("Export the history…", "win.export", "document-save-symbolic", "csv json dataset"),
            (
                "Point at the shared stores…",
                "win.stores",
                "network-server-symbolic",
                "influx neo4j",
            ),
        ):
            found.append(
                Entry(
                    group="This repository",
                    title=title,
                    run=lambda name=action: self.activate_action(name.split(".", 1)[1], None),
                    key=_key_for(action),
                    icon=icon,
                    terms=terms,
                )
            )

        for title, action, icon, terms in (
            (
                "Open another repository…",
                "win.open",
                "document-open-symbolic",
                "switch control plane",
            ),
            (
                "Clone from a git URL…",
                "win.clone",
                "network-workgroup-symbolic",
                "git clone remote",
            ),
        ):
            found.append(
                Entry(
                    group="Switch",
                    title=title,
                    run=lambda name=action: self.activate_action(name.split(".", 1)[1], None),
                    key=_key_for(action),
                    icon=icon,
                    terms=terms,
                )
            )
        for path in self._others():
            found.append(
                Entry(
                    group="Switch",
                    title=f"Open {path.name}",
                    run=lambda one=path: self._open_repository(one),
                    icon="folder-symbolic",
                    terms=str(path),
                )
            )

        for key in PAGES:
            found.append(
                Entry(
                    group="Go to",
                    title=TITLES[key],
                    run=lambda one=key: self._go(one),
                    key=_key_for(f"win.page::{key}"),
                    glyph=key if key in PLACES else "",
                    icon="" if key in PLACES else "go-next-symbolic",
                )
            )
        for title, action in (
            ("Keyboard shortcuts", "win.shortcuts"),
            ("User guide", "win.guide"),
        ):
            found.append(
                Entry(
                    group="Go to",
                    title=title,
                    run=lambda name=action: self.activate_action(name.split(".", 1)[1], None),
                    key=_key_for(action),
                    icon="help-browser-symbolic",
                )
            )
        return found

    # --- reaching outside the window ---

    def _others(self) -> list[Path]:
        """The repositories this machine has driven, minus the one on screen."""
        return [
            path
            for path in recent.remembered(self._settings.state_dir)
            if path != self._settings.repo
        ]

    def _open_another(self) -> None:
        """A folder chooser, then a second window: switching under a live run
        would take the run's window away from it."""
        dialog = Gtk.FileDialog(title="Open a control plane")
        dialog.set_initial_folder(Gio.File.new_for_path(str(self._settings.repo.parent)))
        dialog.select_folder(self, None, self._chosen)

    def _chosen(self, dialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if folder is None or folder.get_path() is None:
            return
        self._open_repository(Path(folder.get_path()))

    def _open_from_url(self) -> None:
        """Clones beside whatever is open, then opens the clone in its own window."""
        CloneDialog(parent=self._settings.repo.parent, on_cloned=self._open_repository).present(
            self
        )

    def _choose_ref(self) -> None:
        """Refuses to switch while anything is running out of this tree.

        Not only this window's runs: the lock is on disk, so a second console
        deploying from the same checkout is exactly the case a ref switch must
        not walk into.
        """
        allowed = [e.name for e in (self._catalog.launchable_environments if self._catalog else [])]
        holder = self._runner.anyone_running()
        RefsDialog(
            repo=self._settings.repo,
            allowed=allowed,
            busy=holder.describe() if holder is not None else "",
            on_switched=self._switched_ref,
        ).present(self)

    def _switched_ref(self, name: str) -> None:
        """Re-reads everything, and says so when the gate itself moved.

        A ref carries its own configuration, so switching can change which
        environments this console will launch against. That is a fact about
        production and it does not get to happen quietly.
        """
        before = {e.name for e in (self._catalog.launchable_environments if self._catalog else [])}
        self._reload()
        after = {e.name for e in (self._catalog.launchable_environments if self._catalog else [])}
        widened = sorted(after - before)
        self._decisions.record(
            kind=decisions_module.REF,
            plane=self._plane.name,
            summary=f"Switched to {name}"
            + (f", which allows {', '.join(widened)}" if widened else ""),
            detail={"ref": name, "widened": widened, "allowed": sorted(after)},
        )
        if widened:
            self._show_notice(
                f"{name} allows {', '.join(widened)}, which the ref before it did not.",
                level="loud",
                action=("Manage environments…", "win.environments"),
            )
        else:
            self._toast(f"On {name}")

    def _open_repository(self, repo: Path) -> None:
        if not recent.is_a_control_plane(repo):
            self._toast(f"{repo.name} has no Makefile, so there is nothing to drive")
            recent.forget(self._settings.state_dir, repo)
            self._hamburger.set_menu_model(menu_module.primary_menu(self._others()))
            return
        recent.remember(self._settings.state_dir, repo)
        window = ConsoleWindow(self.get_application(), self._settings.for_repo(repo))
        window.present()

    def _on_close(self, *_args) -> bool:
        width, height = self.get_default_size()
        geometry.save(self._settings.state_dir, width, height, self.is_maximized())
        return False

    def _open_config(self) -> None:
        path = self._settings.repo / CONFIG_NAME
        if not path.is_file():
            self._toast(f"There is no {CONFIG_NAME} in this repository yet")
            return
        self._launch_file(path)

    def _open_folder(self) -> None:
        self._launch_file(self._settings.repo)

    def _open_guide(self) -> None:
        local = Path(__file__).resolve().parents[3] / "docs" / "user-guide.md"
        if local.is_file():
            self._launch_file(local)
            return
        Gtk.UriLauncher(uri=GUIDE_URL).launch(self, None, None)

    def _launch_file(self, path: Path) -> None:
        launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(str(path)))
        launcher.launch(self, None, self._launched, str(path))

    def _launched(self, launcher, result, path: str) -> None:
        """A desktop with nothing registered for a file type says so, rather than
        appearing to do nothing."""
        try:
            launcher.launch_finish(result)
        except GLib.Error as exc:
            self._toast(f"Could not open {path}: {exc.message}")

    def _copy_details(self) -> None:
        w.copy_to_clipboard("\n".join(f"{name}: {value}" for name, value in self._about_facts()))
        self._toast("Copied: paste these into an issue")

    def _filter_runs(self, key: str) -> None:
        self._runs_filter = key
        self._filter_action.set_state(GLib.Variant.new_string(key))
        self._runs_page.ask(key)

    def _choose_group(self, name: str) -> None:
        self._actions_group = name
        self._render_actions()

    def _remedy(self, name: str) -> None:
        """A step or a verdict names what would help; this is where it happens."""
        doing = {
            setup_module.CHOOSE_ENVIRONMENTS: self._choose_environments,
            setup_module.OPEN_CONFIG: self._open_config,
            setup_module.OPEN_ACTIONS: lambda: self._go(ACTIONS),
            setup_module.OPEN_ENVIRONMENTS: lambda: self._go(ENVIRONMENTS),
            setup_module.OPEN_DELIVERY: lambda: self._go(DELIVERY),
            setup_module.EDIT_OBJECTIVES: self._edit_objectives,
            setup_module.CHECK: self._show_checkup,
            "open-runs": lambda: self._go(RUNS),
            "open-delivery": lambda: self._go(DELIVERY),
            "open-environments": lambda: self._go(ENVIRONMENTS),
            "open-actions": lambda: self._go(ACTIONS),
            "edit-objectives": self._edit_objectives,
            health_module.OPEN_RUNS: lambda: self._go(RUNS),
        }.get(name)
        if doing is not None:
            doing()

    def _choose_environments(self) -> None:
        if self._catalog is None:
            self._toast("The repository cannot be read, so there is nothing to choose from")
            return
        EnvironmentsDialog(
            catalog=self._catalog,
            config=self._config,
            repo=self._settings.repo,
            on_saved=self._environments_saved,
            on_ask=self._ask_hosts,
        ).present(self)

    def _ask_hosts(self, environment: str) -> None:
        """Asks an environment's hosts whether they answer. It changes nothing.

        Recorded like any other run, and labelled as neither a deploy nor a
        cutover, so a probe can never move a delivery measure.
        """
        found = self._catalog.environment(environment) if self._catalog else None
        try:
            built = adhoc.probe(
                inventory=found.inventory if found else "",
                group="all",
                module="ping",
                ansible=self._config.ansible_probe_command,
            )
            active = self._runner.start(
                kind=runner_module.PROBE,
                name=f"reach {environment}",
                environment=environment,
                params={},
                command=built,
                labels={},
                builder=self.builder_for(environment),
                origin=density.BY_HAND,
            )
        except (command_module.ValidationError, RunnerError) as exc:
            self._toast(str(exc))
            return
        self._show_run(active.run, "", active)

    def _environments_saved(self, names: list[str]) -> None:
        before = {e.name for e in (self._catalog.launchable_environments if self._catalog else [])}
        self._reload()
        after = {e.name for e in (self._catalog.launchable_environments if self._catalog else [])}
        self._decisions.record(
            kind=decisions_module.ENVIRONMENTS,
            plane=self._plane.name,
            summary=(
                f"Allowed {', '.join(sorted(names))}"
                if names
                else "Allowed nothing: read-only again"
            ),
            detail={"allowed": sorted(names), "widened": sorted(after - before)},
        )
        self._toast(
            f"{plural(len(names), 'environment')} may now be launched against"
            if names
            else "Read-only again: no environment is allowed"
        )

    def _edit_objectives(self) -> None:
        if self._catalog is None:
            self._toast("The repository cannot be read, so there is nothing to scope them to")
            return
        ObjectivesDialog(
            config=self._config,
            catalog=self._catalog,
            repo=self._settings.repo,
            on_saved=self._objectives_saved,
        ).present(self)

    def _objectives_saved(self, count: int) -> None:
        self._reload()
        self._decisions.record(
            kind=decisions_module.OBJECTIVES,
            plane=self._plane.name,
            summary=saved_message(count),
            detail={"objectives": count},
        )
        self._toast(saved_message(count))

    def _choose_stores(self, *_args) -> None:
        """Where the shared stores are, filled in here rather than in an editor."""
        storesetup.StoresDialog(on_saved=self._stores_saved).present(self)

    def _stores_saved(self) -> None:
        # Re-read rather than remembered: the environment still overrides the
        # file, so what was typed is not necessarily what will be used.
        self._stores = stores_module.configured()
        self._estate.refresh(self._stores, force=True)
        self._toast("Saved: only this account can read that file")

    def _open_stores_folder(self) -> None:
        """The folder the settings file goes in, made if it is not there.

        The directory is created; the file is not. This console does not write
        credentials, and an empty file it created would be one it half owns.
        """
        folder = stores_module.settings_path().parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._toast(f"Could not make {folder}: {exc.strerror}")
            return
        self._launch_file(folder)

    def _export_dataset(self) -> None:
        """The history, in whichever shape the store on the other end reads."""
        ExportDialog(
            runs=self._store.all(self._settings.repo, plane=self._plane.name),
            everything=self._store.all(),
            plane=self._plane.name,
            on_written=self._toast,
        ).present(self)

    def _show_checks(self) -> None:
        sheet = ChecksDialog(repo=self._settings.repo, suite=self._config.validation)
        sheet.connect_done(lambda report: self._checks_recorded(report, started=sheet.started))
        sheet.present(self)

    def _checks_recorded(
        self, report, environment: str = "", sequence: str = "", started: str = ""
    ) -> None:
        """Written down like anything else that ran, so it can be pointed at later."""
        checks_module.record(
            self._store,
            report,
            suite=self._config.validation,
            plane=self._plane.name,
            repo=self._settings.repo,
            environment=environment,
            sequence=sequence,
            started=started,
        )
        self._render(reread_catalog=False)

    def _show_checkup(self) -> None:
        report = doctor_module.examine(
            self._settings.repo,
            history=self._settings.history_path,
            events=self._settings.events_path,
            extra=[availability.finding()],
        )
        CheckupDialog(report, self._settings.repo).present(self)

    def _show_shortcuts(self) -> None:
        menu_module.ShortcutsDialog().present(self)

    # --- data ---

    def _reload(self) -> None:
        """Re-reads the repository, keeping the last good catalogue if it cannot.

        A repository that stops being readable does not empty the window; the failure is
        said out loud and the reading is not restamped.
        """
        try:
            self._config = config_module.load(self._settings.repo)
            self._catalog = catalog_module.build(self._settings.repo, self._config)
            self._catalog_error = ""
            self._loaded_at = time.monotonic()
        except (catalog_module.CatalogError, config_module.ConfigError) as exc:
            self._catalog_error = str(exc)
        self._checkout = repository.read(self._settings.repo)
        if self._stack.get_visible_child_name() == ESTATE:
            self._stores = stores_module.configured()
            self._estate.refresh(self._stores, force=True)
        self._render()

    def _tick(self) -> bool:
        """Cheap refresh: re-reads the store, but not `make help`."""
        if self._catalog is not None:
            self._render(reread_catalog=False)
        self._show_freshness()
        return True

    def _show_freshness(self) -> None:
        """How old the reading is, or that there has never been one."""
        self._rail.show_state(
            actor=self._actor,
            plane=self._plane,
            repo=self._settings.repo,
            readable=self._catalog is not None and not self._catalog_error,
            freshness=(
                text_ago(time.monotonic() - self._loaded_at) if self._loaded_at else "never read"
            ),
            checkout=self._checkout,
        )

    def _render(self, reread_catalog: bool = True) -> None:
        if self._catalog is None:
            self._show_broken()
            return

        self._surface.set_visible_child_name("console")

        if self._catalog_error:
            self._show_notice(
                f"Showing what was read {text_ago(time.monotonic() - self._loaded_at)}: "
                f"the repository cannot be re-read: {self._catalog_error}",
                level="loud",
                action=("What is wrong?", "win.checkup"),
            )
        elif not self._catalog.launchable_environments:
            self._show_notice(
                READ_ONLY, level="setup", action=("Manage environments…", "win.environments")
            )
        else:
            self._notice.set_reveal_child(False)

        self._read_inventories()
        runs = self._store.all(self._settings.repo, plane=self._plane.name)
        for active in self._runner.active():
            for index, run in enumerate(runs):
                if run.id == active.id:
                    runs[index] = active.run
        self._runs = runs

        self._snapshot = metrics.snapshot(
            history_path=self._settings.history_path,
            events_path=self._settings.events_path,
            runs=runs,
            slo_specs=self._config.slos,
            scope=self._config.metric_environments,
        )
        health = health_module.assess(
            catalog=self._catalog, config=self._config, snapshot=self._snapshot, runs=runs
        )
        self._setup = setup_module.assess(
            catalog=self._catalog,
            config=self._config,
            snapshot=self._snapshot,
            runs=runs,
            repo=self._settings.repo,
            history_path=self._settings.history_path,
        )
        self._verdict = verdict_module.decide(
            catalog=self._catalog,
            health=health,
            setup=self._setup,
            runs=runs,
            error=self._catalog_error,
        )
        self._standings = env_module.standings(
            environments=self._catalog.environments,
            runs=runs,
            hosts={
                name: len(answer.hosts)
                for name, answer in self._inventories.items()
                if answer.known
            },
        )

        self._overview.render(
            catalog=self._catalog,
            snapshot=self._snapshot,
            verdict=self._verdict,
            setup=self._setup,
            runs=runs,
            standings=self._standings,
            animate=not geometry.switch(self._settings.state_dir, "reduce-motion"),
        )
        if reread_catalog:
            self._render_actions()
        self._runs_page.render(runs, self._decisions.all(self._plane.name))
        self._open_newest(runs)
        self._environments_page.render(
            self._standings, source=self._catalog.discovery.environment_source
        )
        self._delivery_page.render(
            self._snapshot, scope=", ".join(self._config.metric_environments)
        )
        self._setup_page.render(self._setup)
        self._rail.set_tallies(self._tallies(runs))
        self._show_crumb(self._stack.get_visible_child_name())
        self._show_freshness()

    def _open_newest(self, runs) -> None:
        """The pane beside the list is never blank while there is a run to read.

        It does not navigate: landing on Runs because a history exists is not
        what anybody asked for.
        """
        if self._runs_page.chosen():
            return
        if not runs:
            self._runview.show_nothing(
                "Nothing has run through this console yet. The first run fills the "
                "first gap in the delivery measures."
            )
            return
        # The active run, not just the record of it: handed `None` for a run
        # that is still going, the view has no stream to follow and no way to
        # learn that it ended, so it says `Running` for ever while the list
        # beside it has already moved on.
        self._open_run(runs[0].id, navigate=False)

    def _tallies(self, runs) -> Tallies:
        """The small figures in the rail. An unknown count is nothing, never zero."""
        catalog = self._catalog
        hosts = sum(one.hosts or 0 for one in self._standings)
        return Tallies(
            actions=str(len(catalog.targets)) if catalog.targets else "",
            environments=(
                f"{len(catalog.launchable_environments)}/{len(catalog.environments)}"
                if catalog.environments
                else ""
            ),
            estate=str(hosts) if hosts else "",
            running=any(run.state == "running" for run in runs),
        )

    def _render_actions(self) -> None:
        if self._catalog is None:
            return
        self._actions_page.render(
            catalog=self._catalog,
            config=self._config,
            needle=self._search.get_text().strip(),
            hosts={name: self._hosts_in(name) for name in self._inventories},
            group=self._actions_group,
        )

    def _about_facts(self) -> list[tuple[str, str]]:
        return aboutpage.facts(
            repo=self._settings.repo,
            plane=self._plane,
            state_dir=self._settings.state_dir,
            runs=len(self._runs),
            history=self._settings.history_path,
            events=self._settings.events_path,
        )

    def _render_about(self) -> None:
        self._about_page.render(self._about_facts())

    def _show_broken(self) -> None:
        """The one state with no places to show: say what happened and offer the check."""
        self._show_notice(f"Cannot read the repository: {self._catalog_error}", level="loud")
        self._show_freshness()
        self._surface.set_visible_child_name("broken")
        w.clear(self._broken)

        page = w.empty(
            "This repository cannot be read",
            f"{self._catalog_error}\n\nThe console derives everything it offers from "
            "the repository, so until that can be read there is nothing to show. "
            "Nothing has been changed and nothing has run.",
            "dialog-error-symbolic",
        )
        buttons = w.row(10)
        buttons.set_halign(Gtk.Align.CENTER)
        buttons.append(w.button("Check this repository", "go", action="win.checkup"))
        buttons.append(w.button("Open the folder", "quiet", action="win.folder"))
        buttons.append(w.button("Try again", "quiet", action="win.refresh"))
        page.set_child(buttons)
        self._broken.append(page)

    def _show_notice(self, text: str, level: str = "quiet", action=None) -> None:
        self._notice.set_child(w.notice(text, level, action))
        self._notice.set_reveal_child(True)

    # --- launching ---

    def _open_launch(self, target) -> None:
        if target is None:
            self._toast("There is no such action in this repository")
            return
        LaunchDialog(
            target=target,
            catalog=self._catalog,
            config=self._config,
            repo=self._settings.repo,
            on_launch=self._launch,
        ).present(self)

    def _launch_simply(self, name: str, environment: str, dry_run: bool) -> None:
        """The composer's own launch: the two things every run needs, and no more.

        An action with parameters it insists on cannot be launched this way, so
        the full form opens instead of the run being refused.
        """
        target = self._catalog.target(name) if self._catalog else None
        if target is None:
            self._toast(f"{name} is not an action in this {PLANE}")
            return
        if any(getattr(one, "required", False) for one in target.params.values()):
            self._toast(f"{name} needs its parameters filling in first")
            self._open_launch(target)
            return
        self._launch(target, environment, {}, dry_run)

    def _hosts_in(self, environment: str) -> tuple[str, ...]:
        answer = self._inventories.get(environment)
        return answer.hosts if answer is not None and answer.known else ()

    def _read_inventories(self) -> None:
        """Asks Ansible what each launchable environment holds, on a thread.

        Once each, when the catalogue is read. The answer is what a run records
        as its builder, and a run may not wait for it: an inventory plugin
        that calls a cloud API takes seconds this console does not have.
        """
        if self._catalog is None:
            return
        wanted = [
            e
            for e in self._catalog.launchable_environments
            if e.inventory and e.name not in self._inventories
        ]
        for environment in wanted:
            threading.Thread(
                target=self._ask_inventory,
                args=(environment.name, environment.inventory),
                daemon=True,
                name=f"inventory-{environment.name}",
            ).start()

    def _ask_inventory(self, name: str, path: str) -> None:
        answer = inventory_module.read(self._settings.repo, path)
        GLib.idle_add(self._inventory_read, name, answer)

    def _inventory_read(self, name: str, answer) -> bool:
        """An answer that lands after the page was drawn still has to reach it."""
        self._inventories[name] = answer
        if self._catalog is not None:
            self._render(reread_catalog=True)
        return False

    def builder_for(self, environment: str) -> str:
        """The host that builds for this environment, or nothing yet known.

        Empty is honest: the record then says the builder was not known rather
        than naming the wrong one.
        """
        answer = self._inventories.get(environment)
        if answer is None or not answer.known:
            return ""
        group = answer.group("builder")
        return ", ".join(group.hosts) if group else ""

    def _launch(self, target, environment: str, params: dict, dry_run: bool, options=None) -> None:
        book = self._config.runbook_for(target.name)
        refused = runbook_module.refusals(
            book,
            hosts=len(self._hosts_in(environment)),
            ref=self._checkout.branch,
            dirty=self._checkout.dirty,
        )
        if refused and not dry_run:
            # Every broken policy at once: fixing one and being refused again
            # is how somebody stops reading the reason.
            self._show_notice(
                " ".join(one.reason for one in refused),
                level="loud",
                action=("Open the configuration", "win.configure"),
            )
            self._toast(f"{target.name} was refused by this repository's own policy")
            return
        order = runbook_module.steps(book)
        self._sequence = _Sequence(
            book=book,
            environment=environment,
            params=params,
            dry_run=dry_run,
            options=options,
            # One id for the launch, carried by every record it produces. A
            # single-step runbook is not a launch worth relating anything to.
            id=new_id() if len(order) > 1 else "",
        )
        self._run_step(order[0])

    def _run_step(self, step) -> None:
        """One step of a runbook, and a watcher that starts the next when it ends."""
        sequence = self._sequence
        if sequence is None:
            return
        if step.kind == runbook_module.VALIDATE:
            self._validate_step(step)
            return
        target = self._catalog.target(step.target) if self._catalog else None
        if target is None:
            self._toast(f"{step.target} is not an action in this {PLANE}")
            self._sequence = None
            return
        first = step.kind == runbook_module.OPERATION
        try:
            built = command_module.for_target(
                target=target,
                environment=sequence.environment,
                params=sequence.params if first else {},
                config=self._config,
                dry_run=sequence.dry_run,
                catalog=self._catalog,
                options=sequence.options if first else None,
            )
            active = self._runner.start(
                kind="target" if first else step.kind,
                name=target.name,
                environment=sequence.environment,
                params=sequence.params if first else {},
                command=built,
                # Only the operation counts as a deploy: a precheck that
                # carried the label would move a delivery measure on its own.
                labels=self._config.labels_for(target.name) if first else {},
                builder=self.builder_for(sequence.environment),
                sequence=sequence.id,
                # The operation is what somebody pressed the button for, so it
                # always keeps its own row; the checks around it may fold.
                origin=density.BY_HAND if first else density.BY_STEP,
            )
        except (command_module.ValidationError, RunnerError) as exc:
            self._toast(str(exc))
            self._sequence = None
            return

        self._show_run(active.run, "", active)
        self._toast(step.sentence)
        if len(runbook_module.steps(sequence.book)) > 1:
            self._watch_step(active, step)

    def _validate_step(self, step) -> None:
        """The repository's own checks, before anything reaches a host.

        Shown rather than run silently: a check that gates a deploy is one
        somebody has to be able to read the output of.
        """
        dialog = ChecksDialog(
            repo=self._settings.repo,
            suite=self._config.validation,
            on_done=lambda report: self._checks_done(step, report, dialog.started),
        )
        dialog.present(self)
        if validation_module.available(self._config.validation):
            # Nothing to run: a suite that cannot run must not silently pass a
            # gate somebody declared.
            self._sequence = None
            self._toast("The checks could not run, so nothing was launched")
            return
        dialog.start()

    def _checks_done(self, step, report, started: str = "") -> None:
        sequence = self._sequence
        if sequence is None:
            return
        self._checks_recorded(report, sequence.environment, sequence.id, started)
        following = runbook_module.after(sequence.book, step.kind, report.ok)
        if following is None:
            self._sequence = None
            failed = ", ".join(one.check.name for one in report.failed)
            self._show_notice(
                f"{failed} did not pass, so {sequence.book.target} was not run.",
                level="loud",
            )
            return
        GLib.idle_add(self._run_step, following)

    def _watch_step(self, active, step) -> None:
        """Waits for this step to end, then asks the runbook what follows it."""

        def look() -> bool:
            if not active.finished:
                return True
            following = (
                runbook_module.after(
                    self._sequence.book if self._sequence else None, step.kind, active.run.ok
                )
                if self._sequence
                else None
            )
            if following is None:
                self._sequence_ended(step, active)
                return False
            GLib.idle_add(self._run_step, following)
            return False

        GLib.timeout_add(STEP_POLL_MS, look)

    def _sequence_ended(self, step, active) -> None:
        """Says what a stopped sequence means, which is not always a failure."""
        book = self._sequence.book if self._sequence else None
        self._sequence = None
        if book is None or active.run.ok:
            if step.kind == runbook_module.POSTCHECK:
                self._toast(f"{book.target} ran and its postcheck passed")
            return
        if step.kind == runbook_module.PRECHECK:
            self._show_notice(
                f"{step.target} failed, so {book.target} was not run.",
                level="loud",
            )
        elif step.kind == runbook_module.POSTCHECK:
            self._show_notice(
                f"{book.target} ran and {step.target} did not pass. The change is not verified.",
                level="loud",
            )
        elif book.recovery:
            self._show_notice(
                f"{book.target} failed. This repository declares {book.recovery} as its recovery.",
                level="loud",
                action=(f"Run {book.recovery}…", "win.recover"),
            )
            self._recovery = book.recovery

    def _run_recovery(self) -> None:
        """Only ever what the configuration declared, and only after a failure."""
        target = self._catalog.target(self._recovery or "") if self._catalog else None
        if target is not None:
            self._open_launch(target)
        self._recovery = ""

    def _open_run(self, run_id: str, navigate: bool = True) -> None:
        """A run that has ended is a stored run, whoever still holds it in memory.

        The runner keeps every run it started, finished or not. A finished one has no
        stream left to fill the view, so it has to be read back from the store.
        """
        active = self._runner.get(run_id)
        if active is not None and active.finished:
            active = None
        run = active.run if active is not None else self._store.get(run_id)
        if run is None:
            self._toast(f"no run {run_id}")
            return
        output = "" if active is not None else self._store.output(run_id)
        self._show_run(run, output, active, navigate=navigate)

    def _show_run(self, run, output: str, active, navigate: bool = True) -> None:
        self._runview.show(run, output, active)
        self._runs_page.select(run.id)
        if navigate:
            self._go(RUNS)

    def _relaunch(self, run_id: str, only_failures: bool = False) -> None:
        """Runs a recorded run again, or says why it cannot be."""
        run = self._store.get(run_id)
        if run is None:
            self._toast("That run is no longer in the history")
            return
        replay = (
            relaunch_module.against_failures(run) if only_failures else relaunch_module.again(run)
        )
        if not replay.possible:
            self._toast(replay.refusal.capitalize())
            return
        try:
            active = self._runner.start(
                kind=run.kind,
                name=run.name,
                environment=run.environment,
                params=run.params,
                command=replay.command,
                labels=run.labels,
                # Read again rather than copied: the inventory may name a
                # different builder than it did when the first run went out.
                builder=self.builder_for(run.environment),
                origin=density.BY_REPEAT,
            )
        except RunnerError as exc:
            self._toast(str(exc))
            return
        self._show_run(active.run, "", active)
        where = (
            f" against {plural(len(replay.limited_to), 'host')} that failed"
            if replay.limited_to
            else ""
        )
        self._toast(f"{run.name} running again{where}")

    def _cancel_run(self, run_id: str) -> None:
        active = self._runner.get(run_id)
        if active is not None and active.cancel():
            self._toast("Cancelling: the process was signalled")
        else:
            self._toast("That run has already finished")

    def _toast(self, message: str) -> None:
        """A short sentence, and one that cannot ask for more width than there is."""
        toast = Adw.Toast(timeout=4)
        said = w.label(message, wrap=True, xalign=0.5)
        said.set_justify(Gtk.Justification.CENTER)
        # A wrapping label's minimum width is its longest unbreakable word, and
        # this console says things like `~/.config/ordane/stores.env`, which is
        # one word. Breaking inside a word when there is no other way is what
        # keeps that minimum to a character instead of a path.
        said.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        # And its natural width should not grow with the message either.
        said.set_natural_wrap_mode(Gtk.NaturalWrapMode.NONE)
        # Clamped in pixels: whatever the font, the toast cannot ask for more
        # than this, so it cannot ask for more than a narrow window has.
        toast.set_custom_title(
            Adw.Clamp(
                maximum_size=TOAST_WIDTH_PX,
                tightening_threshold=TOAST_WIDTH_PX,
                child=said,
            )
        )
        self._toasts.add_toast(toast)


@dataclass(frozen=True)
class _Sequence:
    """What a launch is running, kept while its steps go one after another."""

    book: object
    environment: str
    params: dict
    dry_run: bool
    options: object = None
    # Minted once per launch and carried by every record it produces, so the
    # checks, the precheck, the operation and the postcheck are one thing in
    # the history rather than four that happen to be close together.
    id: str = ""


def _key_for(action: str) -> str:
    key = for_action(action)
    return key.pretty if key is not None else ""


def _well(child: Gtk.Widget) -> Gtk.Widget:
    """The content well: left-aligned inside the stage, and it fills the height."""
    holder = w.clamp(child)
    holder.set_vexpand(True)
    return holder


def breakpoint_for(window) -> Adw.Breakpoint:
    """Below this the rail is taking width the content needs, so it folds away.

    The two places that are a list beside a pane stack instead, because a
    296 px list and a run's own detail cannot both keep their width — and a
    window that demands more than it has does not lay out at all.
    """
    condition = Adw.BreakpointCondition.parse("max-width: 1100px")
    point = Adw.Breakpoint.new(condition)
    point.add_setter(window.split, "collapsed", True)

    # The orientation is set from the signals rather than by `add_setter`. A
    # setter for an enum property applied nothing here and said nothing about
    # it, so the two split pages stayed side by side in a window too narrow to
    # hold them and the layout asked for more width than it had.
    stacked = (window._actions_page, window._runs_page)

    def lay_out(_point, orientation) -> None:
        for page in stacked:
            page.set_orientation(orientation)

    point.connect("apply", lay_out, Gtk.Orientation.VERTICAL)
    point.connect("unapply", lay_out, Gtk.Orientation.HORIZONTAL)
    return point


def resolve_repo(raw: Path) -> Path:
    return raw.expanduser().resolve()
