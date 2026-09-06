"""The main window: four views over one engine, and one place that refreshes them."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from ..core import adhoc, identity, plane, recent, repository, search  # noqa: E402
from ..core import catalog as catalog_module  # noqa: E402
from ..core import command as command_module  # noqa: E402
from ..core import config as config_module  # noqa: E402
from ..core import doctor as doctor_module  # noqa: E402
from ..core import inventory as inventory_module  # noqa: E402
from ..core import runbook as runbook_module  # noqa: E402
from ..core import validation as validation_module  # noqa: E402
from ..core.config import CONFIG_NAME  # noqa: E402
from ..insight import health as health_module  # noqa: E402
from ..insight import metrics  # noqa: E402
from ..insight import relaunch as relaunch_module  # noqa: E402
from ..insight import runs as runs_module  # noqa: E402
from ..insight import stores as stores_module  # noqa: E402
from ..presentation.language import PLANE  # noqa: E402
from ..presentation.text import ago as text_ago  # noqa: E402
from ..presentation.text import day, moment, plural  # noqa: E402
from ..record import checks as checks_module  # noqa: E402
from ..record import decisions as decisions_module  # noqa: E402
from ..record import runner as runner_module  # noqa: E402
from ..record.runner import Runner, RunnerError  # noqa: E402
from ..record.store import RunStore, new_id  # noqa: E402
from . import availability, geometry, storesetup  # noqa: E402
from . import menu as menu_module  # noqa: E402
from . import widgets as w  # noqa: E402
from .checks import ChecksDialog  # noqa: E402
from .checkup import CheckupDialog  # noqa: E402
from .dashboard import Dashboard  # noqa: E402
from .dataset import ExportDialog  # noqa: E402
from .environments import EnvironmentsDialog  # noqa: E402
from .estate import Estate  # noqa: E402
from .folding import Folding  # noqa: E402
from .launch import LaunchDialog  # noqa: E402
from .objectives import ObjectivesDialog, saved_message  # noqa: E402
from .preferences import Preferences  # noqa: E402
from .refs import CloneDialog, RefsDialog  # noqa: E402
from .runview import RunView  # noqa: E402
from .sidebar import Sidebar  # noqa: E402
from .trail import Trail  # noqa: E402

REFRESH_SECONDS = 5

# How many runs the page draws. Beyond this the reader is searching, not
# scrolling, and the terminal front end is the better tool for it.
HISTORY_SECTION = "run-history"
DECISIONS_SECTION = "decisions"
DECISIONS_SHOWN = 12

# How often a sequence looks to see whether its current step has ended. Short
# enough that a check and the operation after it feel like one action.
STEP_POLL_MS = 250

# How wide a toast is allowed to get before it wraps. A toast is a sentence,
# and one long enough to need the whole window belongs in a notice.
# How wide a toast may get, in pixels. It was a character count, which is a
# guess about the font: 56 characters is 1236 px in the font a CI runner
# has and comfortably less here, so the overlay asked for more width than
# the window had and said so, hundreds of times.
TOAST_WIDTH_PX = 420

DECISION_ICONS = {
    "ref": "media-playlist-repeat-symbolic",
    "environments": "preferences-system-symbolic",
    "objectives": "emblem-ok-symbolic",
}
# X11 and Wayland both number the side buttons this way, and every other
# application on this desktop reads them as back and forward.
MOUSE_BACK = 8
MOUSE_FORWARD = 9

RUNS_SHOWN = 60
APP_NAME = "Ordane"
PAGES = ("dashboard", "actions", "runs", "estate")

READ_ONLY = "Read-only: no environment has been chosen yet"

GUIDE_URL = f"{menu_module.PROJECT}/blob/main/docs/user-guide.md"


class ConsoleWindow(Adw.ApplicationWindow):
    """Owns the store, the runner and the four pages."""

    def __init__(self, application, settings) -> None:
        super().__init__(application=application, title=APP_NAME)
        width, height, maximised = geometry.restore(settings.state_dir)
        self.set_default_size(width, height)
        # A breakpoint needs the window to declare how small it may get, and
        # below this the rail and a command row cannot both fit.
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
        self._runs_signature: tuple | None = None
        self._actions()
        self._build()
        menu_module.install_accelerators(application)
        self._reload()
        if settings.page in PAGES:
            self._stack.set_visible_child_name(settings.page)
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._tick)

    # --- what the window can be asked to do ---

    def _actions(self) -> None:
        """One action per thing the menu, the keyboard and a button all reach."""
        page = Gio.SimpleAction.new_stateful(
            "page", GLib.VariantType.new("s"), GLib.Variant.new_string("dashboard")
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
            ("back", self._leave_run),
            ("go-back", self._go_back),
            ("go-forward", self._go_forward),
            ("find", self._focus_search),
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
            ("preferences", self._show_preferences),
            ("open", self._open_another),
            ("clone", self._open_from_url),
            ("recover", self._run_recovery),
            ("refs", self._choose_ref),
            ("shortcuts", self._show_shortcuts),
            ("guide", self._open_guide),
            ("about", self._show_about),
            ("close", self.close),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, run=handler: run())
            self.add_action(action)

    # --- layout ---

    def _build(self) -> None:
        self._folding = Folding(self._settings.state_dir)
        self._trail = Trail()
        self._retracing = False
        self._dashboard = Dashboard(self._open_run, self._remedy, self._folding)
        self._actions_page = w.box(spacing=16)
        self._runs_page = w.box(spacing=16)
        self._runview = RunView(
            self._cancel_run,
            self._relaunch,
            steps_of=self._store.steps_of,
            on_open=self._open_run,
            notice_task=lambda: self._config.notifications_task,
        )

        self._stack = Adw.ViewStack()
        self._stack.add_titled_with_icon(
            self._dashboard, "dashboard", "Health", "utilities-system-monitor-symbolic"
        )
        # The search has a bar of its own rather than living in the rail: it is
        # how a control plane with thirty-five targets is used at all, and it
        # cannot depend on a rail somebody has turned off.
        self._search = Gtk.SearchEntry(placeholder_text="Find a target")
        self._search.connect("search-changed", lambda *_: self._render_actions())
        self._search_bar = Gtk.SearchBar(child=self._search, key_capture_widget=self)
        self._search_bar.connect_entry(self._search)
        self._stack.add_titled_with_icon(
            w.scrolled(w.clamp(self._actions_page)),
            "actions",
            "Actions",
            "media-playback-start-symbolic",
        )
        self._runs_filter = runs_module.ALL
        self._actions_group: str | None = None
        self._last_run = None
        # What each environment holds, asked once and remembered. It is read
        # off the launch path on purpose: a run must not wait on a cloud API.
        self._inventories: dict[str, inventory_module.Inventory] = {}
        self._sequence: _Sequence | None = None
        self._recovery = ""
        self._stack.add_titled_with_icon(
            w.scrolled(w.clamp(self._runs_page)), "runs", "Runs", "document-open-recent-symbolic"
        )
        # Its own view, because it is the only one that needs a network. Health
        # reads files on this machine and keeps working when nothing is up.
        self._estate = Estate()
        self._estate._on_copied = self._toast
        self._stack.add_titled_with_icon(
            self._estate, "estate", "Estate", "network-server-symbolic"
        )
        # Always offered. It was hidden until a store was configured, which
        # made the whole view invisible to anybody who did not already know it
        # existed, and its unconfigured state is exactly where the
        # instructions for configuring it belong.
        self._stores = stores_module.configured()
        self._stack.add_titled_with_icon(self._runview, "run", "Run", "utilities-terminal-symbolic")
        self._stack.get_page(self._runview).set_visible(False)
        self._stack.connect("notify::visible-child-name", self._on_page_changed)

        header = Adw.HeaderBar()
        self._switcher = Adw.ViewSwitcher(stack=self._stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(self._switcher)

        self._rail_button = Gtk.ToggleButton(
            icon_name="sidebar-show-symbolic", tooltip_text="Show or hide the rail", active=True
        )
        header.pack_start(self._rail_button)
        # Which control plane, and whether it can be read: in the chrome, so it
        # is legible without keeping a rail open to look at it.
        self._plane_button = w.PlaneButton(self._show_checkup)
        header.pack_start(self._plane_button)
        self._navigation = geometry.navigation(self._settings.state_dir)

        self._hamburger = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            menu_model=menu_module.primary_menu(self._others()),
            tooltip_text="Main menu",
        )
        header.pack_end(self._hamburger)
        reload_button = Gtk.Button(
            icon_name="view-refresh-symbolic", tooltip_text="Re-read the repository (Ctrl+R)"
        )
        reload_button.set_action_name("win.refresh")
        header.pack_end(reload_button)
        find = Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text="Find a target")
        find.bind_property(
            "active",
            self._search_bar,
            "search-mode-enabled",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )
        header.pack_end(find)

        self._notice = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._toasts = Adw.ToastOverlay()

        # Running as root is a standing fact about the whole session, so it is
        # not the notice: that one comes and goes with the repository.
        self._actor = identity.who()
        self._root_banner = Adw.Banner(
            title=f"Running as root: {self._actor.summary}. {identity.ROOT_WARNING}",
            revealed=self._actor.is_root,
        )
        self._root_banner.add_css_class("error")

        # A repository that cannot be read is shown in place of the views rather
        # than behind a notice over four empty pages.
        self._broken = w.box(spacing=16)
        self._surface = Gtk.Stack()
        self._surface.add_named(self._stack, "console")
        self._surface.add_named(self._broken, "broken")

        self._sidebar = Sidebar()
        self.split = Adw.OverlaySplitView(
            sidebar=self._sidebar, content=self._surface, max_sidebar_width=340
        )
        self.split.bind_property(
            "show-sidebar",
            self._rail_button,
            "active",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )

        # Claimed on the capture phase so a row underneath cannot swallow it,
        # and on button 0 because GTK names only the first three.
        buttons = Gtk.GestureClick(button=0, propagation_phase=Gtk.PropagationPhase.CAPTURE)
        buttons.connect("pressed", self._on_mouse_button)
        self.add_controller(buttons)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self._search_bar)
        toolbar.add_top_bar(self._root_banner)
        toolbar.add_top_bar(self._notice)
        toolbar.set_content(self.split)
        self._toasts.set_child(toolbar)
        self.set_content(self._toasts)
        self.add_breakpoint(breakpoint_for(self))
        self._apply_navigation()

    def _remember_page(self) -> None:
        name = self._stack.get_visible_child_name() or ""
        # The run view comes and goes with one run; it is not a place to
        # return to, and putting it on the trail would make back a loop.
        if not self._retracing and name != "run":
            self._trail.visit(name)

    def _on_page_changed(self, *_args) -> None:
        """However the page changed: a key, an action, or the switcher clicked.

        The estate used to be asked from `_go`, which the view switcher does
        not call: clicking the tab left it on its spinner for ever.
        """
        name = self._stack.get_visible_child_name()
        self._remember_page()
        if name in PAGES:
            self._page_action.set_state(GLib.Variant.new_string(name))
        if name == "estate":
            # Re-read: the settings file may have been written since the window
            # opened, which is the commonest way this gets configured.
            self._stores = stores_module.configured()
            self._estate.refresh(self._stores)

    def _go(self, name: str) -> None:
        self._stack.set_visible_child_name(name)

    # --- back and forward, which the mouse has two buttons for ---

    def _retrace(self, page: str | None) -> None:
        """Steps to a page without recording the step as somewhere new."""
        if page is None:
            return
        self._retracing = True
        try:
            self._go(page)
        finally:
            self._retracing = False

    def _go_back(self) -> None:
        # The run view is not on the trail; leaving it is what back means there.
        if self._stack.get_visible_child_name() == "run":
            self._leave_run()
            return
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
        if self._stack.get_visible_child_name() == "run":
            self._runview.find()
            return
        self._go("actions")
        self._search_bar.set_search_mode(True)
        self._search.grab_focus()

    def _leave_run(self) -> None:
        if self._stack.get_visible_child_name() == "run":
            self._runview.stop()
            self._go("runs")
        elif self._search.get_text():
            self._search.set_text("")
        elif self._search_bar.get_search_mode():
            self._search_bar.set_search_mode(False)

    # --- reaching outside the window ---

    def _toggle_rail(self) -> None:
        self.split.set_show_sidebar(not self.split.get_show_sidebar())

    def _apply_navigation(self) -> None:
        """The rail, the menu, or both: whichever this person keeps.

        The menu is never taken away on a narrow window: the rail folds there,
        and hiding both would leave nine actions with nowhere to be reached.
        """
        keeps_rail = self._navigation in (geometry.RAIL, geometry.BOTH)
        self.split.set_show_sidebar(keeps_rail)
        self._rail_button.set_visible(keeps_rail or self.split.get_collapsed())
        self._hamburger.set_visible(
            self._navigation in (geometry.MENU, geometry.BOTH) or not keeps_rail
        )

    def _choose_navigation(self, chosen: str) -> None:
        self._navigation = chosen
        geometry.save_navigation(self._settings.state_dir, chosen)
        self._apply_navigation()

    def _show_preferences(self) -> None:
        Preferences(self._navigation, self._choose_navigation).present(self)

    def _others(self) -> list[Path]:
        """The control planes this machine has driven, minus the one on screen."""
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

    # --- where the control plane comes from, and which ref of it runs ---

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

    def _filter_runs(self, key: str) -> None:
        self._runs_filter = key
        self._filter_action.set_state(GLib.Variant.new_string(key))
        self._runs_signature = None
        self._render(reread_catalog=False)

    def _remedy(self, name: str) -> None:
        """A concern names what would help; this is where the window has one."""
        doing = {
            health_module.CHOOSE_ENVIRONMENTS: self._choose_environments,
            health_module.OPEN_CONFIG: self._open_config,
            health_module.OPEN_RUNS: lambda: self._go("runs"),
            health_module.CHECK: self._show_checkup,
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
        self._runs_signature = None
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

    def _show_about(self) -> None:
        menu_module.about_dialog(self._settings.repo).present(self)

    # --- data ---

    def _reload(self) -> None:
        """Re-reads the repository, keeping the last good catalogue if it cannot.

        On the estate this also asks the stores again, so it is one key for bringing any
        view up to date.

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
        if self._stack.get_visible_child_name() == "estate":
            self._stores = stores_module.configured()
            self._estate.refresh(self._stores, force=True)
        self._runs_signature = None
        self._render()

    def _tick(self) -> bool:
        """Cheap refresh: re-reads the store, but not `make help`."""
        if self._catalog is not None:
            self._render(reread_catalog=False)
        self._show_freshness()
        return True

    def _show_freshness(self) -> None:
        """How old the reading is, or that there has never been one."""
        state = dict(
            actor=self._actor,
            plane=self._plane,
            repo=self._settings.repo,
            readable=self._catalog is not None and not self._catalog_error,
            freshness=(
                text_ago(time.monotonic() - self._loaded_at) if self._loaded_at else "never read"
            ),
            checkout=self._checkout,
        )
        self._sidebar.show_state(**state)
        self._plane_button.render(**state)

    def _render(self, reread_catalog: bool = True) -> None:
        if self._catalog is None:
            self._show_broken()
            return

        self._surface.set_visible_child_name("console")
        self._switcher.set_visible(True)

        if self._catalog_error:
            self._show_notice(
                f"Showing what was read {text_ago(time.monotonic() - self._loaded_at)}: "
                f"the repository cannot be re-read: {self._catalog_error}",
                level="loud",
                action=("What is wrong?", "win.checkup"),
            )
        elif not self._catalog.launchable_environments:
            self._show_notice(READ_ONLY, action=("Manage environments…", "win.environments"))
        else:
            self._notice.set_reveal_child(False)

        self._read_inventories()
        runs = self._store.all(self._settings.repo, plane=self._plane.name)
        for active in self._runner.active():
            for index, run in enumerate(runs):
                if run.id == active.id:
                    runs[index] = active.run
        # Kept so the Actions header does not read the history again on every
        # keystroke in the search field.
        self._last_run = runs[0] if runs else None

        snapshot = metrics.snapshot(
            history_path=self._settings.history_path,
            events_path=self._settings.events_path,
            runs=runs,
            slo_specs=self._config.slos,
            scope=self._config.metric_environments,
        )
        health = health_module.assess(
            catalog=self._catalog, config=self._config, snapshot=snapshot, runs=runs
        )
        self._dashboard.render(
            catalog=self._catalog,
            snapshot=snapshot,
            health=health,
            runs=runs,
            repo=self._settings.repo,
        )
        if reread_catalog:
            self._render_actions()
        self._render_runs(runs)
        self._show_freshness()

    def _show_broken(self) -> None:
        """The one state with no views to show: say what happened and offer the check."""
        self._show_notice(f"Cannot read the repository: {self._catalog_error}", level="loud")
        self._show_freshness()
        self._surface.set_visible_child_name("broken")
        self._switcher.set_visible(False)
        _empty(self._broken)

        page = w.empty(
            "This repository cannot be read",
            f"{self._catalog_error}\n\nThe console derives everything it offers from "
            "`make help`, so until that runs there is nothing to show. Nothing has been "
            "changed and nothing has run.",
            "dialog-error-symbolic",
        )
        buttons = w.box(Gtk.Orientation.HORIZONTAL, 10)
        buttons.set_halign(Gtk.Align.CENTER)
        for text_label, action_name, style in (
            ("Check this control plane", "win.checkup", "suggested-action"),
            ("Open the folder", "win.folder", ""),
            ("Try again", "win.refresh", ""),
        ):
            button = Gtk.Button(label=text_label)
            button.add_css_class("pill")
            if style:
                button.add_css_class(style)
            button.set_action_name(action_name)
            buttons.append(button)
        page.set_child(buttons)
        self._broken.append(page)

    def _show_notice(self, text: str, level: str = "quiet", action=None) -> None:
        self._notice.set_child(w.notice(text, level, action))
        self._notice.set_reveal_child(True)

    # --- the actions page ---

    def _render_actions(self) -> None:
        _empty(self._actions_page)
        needle = self._search.get_text().strip()
        launchable = bool(self._catalog.launchable_environments)

        if not launchable:
            self._actions_page.append(self._read_only_page())
            return

        self._actions_page.append(self._actions_header())
        matches = search.rank(self._catalog.targets, needle)
        if needle and not matches:
            self._actions_page.append(
                w.empty(
                    f"Nothing here is called “{needle}”",
                    "The search covers a target's name and the description `make help` "
                    "prints beside it.",
                    "system-search-symbolic",
                )
            )
            return

        if needle:
            self._actions_page.append(self._ranked(matches, needle))
            return
        self._actions_page.append(self._by_group([m.target for m in matches]))

    def _actions_header(self) -> Gtk.Widget:
        beside = None
        if self._last_run is not None:
            beside = w.label(
                f"Last run: {self._last_run.name}, {moment(self._last_run.started)}",
                "metric-detail",
            )
        return w.page_header(
            "Actions",
            f"{plural(len(self._catalog.targets), 'target')}, in the groups this repository "
            f"declares and the order it declares them. Anything that changes something "
            f"says so beside its name.",
            beside,
        )

    def _by_group(self, targets) -> Gtk.Widget:
        """One group at a time, chosen from a column: eleven targets scroll, forty do not."""
        groups: dict[str, list] = {}
        for target in targets:
            groups.setdefault(target.group, []).append(target)
        # The config declares its groups in a working order; sorting them
        # alphabetically would throw that decision away.
        names = self._config.sort_groups(groups)
        if len(names) < 2:
            holder = w.box(spacing=16)
            for name in names:
                holder.append(self._group_rows(name, groups[name], titled=True))
            return holder

        if self._actions_group not in names:
            self._actions_group = names[0]
        chosen = self._actions_group

        body = w.box(Gtk.Orientation.HORIZONTAL, 20)
        column = w.box(spacing=2)
        column.add_css_class("group-column")
        # It expands so its rule runs the height of the region rather than
        # stopping under the last group, which read as a torn edge.
        column.set_vexpand(True)
        for name in names:
            column.append(self._group_row(name, len(groups[name]), name == chosen))
        body.append(column)

        # No heading over the rows: the column already says which group this is.
        rows = self._group_rows(chosen, groups[chosen], titled=False)
        rows.set_hexpand(True)
        body.append(rows)
        return body

    def _group_row(self, name: str, count: int, chosen: bool) -> Gtk.Widget:
        line = w.box(Gtk.Orientation.HORIZONTAL, 10)
        label = w.label(name, "group-name")
        label.set_hexpand(True)
        label.set_ellipsize(3)
        line.append(label)
        line.append(w.label(str(count), "group-count"))
        button = Gtk.Button(child=line)
        button.add_css_class("flat")
        button.add_css_class("group-row")
        if chosen:
            button.add_css_class("chosen")
        button.set_tooltip_text(f"{plural(count, 'target')} in {name}")
        button.connect("clicked", lambda _b, n=name: self._choose_group(n))
        return button

    def _choose_group(self, name: str) -> None:
        self._actions_group = name
        self._render_actions()

    def _group_rows(self, name: str, targets, titled: bool) -> Gtk.Widget:
        group = Adw.PreferencesGroup(title=name if titled else "")
        for target in targets:
            group.add(self._target_row(target))
        return group

    def _read_only_page(self) -> Gtk.Widget:
        """The dead end this used to be: forty greyed-out buttons and no way forward."""
        page = w.empty(
            "Nothing can be launched yet",
            f"{plural(len(self._catalog.targets), 'target')} were read from `make help`, and "
            "none of them may run until you say which environments this console is allowed "
            f"to reach. Nothing is chosen for you, because that is a decision about "
            f"production.\n\nThe choice is stored in {CONFIG_NAME} in the repository.",
            "changes-prevent-symbolic",
        )
        button = Gtk.Button(label="Manage environments…")
        button.add_css_class("suggested-action")
        button.add_css_class("pill")
        button.set_halign(Gtk.Align.CENTER)
        button.set_action_name("win.environments")
        page.set_child(button)
        return page

    def _ranked(self, matches, needle: str) -> Gtk.Widget:
        """While searching the list is one ranked run, because a group heading would
        hide which match is the best one."""
        group = Adw.PreferencesGroup(
            title=f"{plural(len(matches), 'match')} for “{needle}”",
            description="Best match first.",
        )
        for match in matches:
            row = self._target_row(match.target)
            row.set_subtitle(f"{match.target.description} · {match.reason}")
            group.add(row)
        return group

    def _target_row(self, target) -> Adw.ActionRow:
        row = Adw.ActionRow(title=target.name, subtitle=target.description, activatable=True)
        row.set_subtitle_lines(2)
        book = self._config.runbook_for(target.name)
        if book.stale():
            stale = w.badge("STALE", "medium")
            stale.set_tooltip_text(
                f"Last reviewed {book.reviewed}. Nobody has looked at this runbook in a year."
            )
            row.add_suffix(stale)
        chip = w.danger_chip(target.danger)
        if chip is not None:
            row.add_suffix(chip)
        button = Gtk.Button(label="Run…", valign=Gtk.Align.CENTER)
        button.add_css_class("pill")
        button.set_tooltip_text(self._where(target))
        button.connect("clicked", lambda _b, t=target: self._open_launch(t))
        row.add_suffix(button)
        row.connect("activated", lambda _r, t=target: self._open_launch(t))
        w.attach_context_menu(
            row,
            [
                (f"Run {target.name}…", lambda t=target: self._open_launch(t)),
                (
                    "Copy the make command",
                    lambda t=target: self._copy(f"make {t.name}", "command"),
                ),
            ],
        )
        return row

    def _where(self, target) -> str:
        names = target.fixed_environment or ", ".join(
            e.name for e in self._catalog.launchable_environments
        )
        return f"Set up a run of {target.name} against {names}"

    def _copy(self, text: str, what: str) -> None:
        w.copy_to_clipboard(text)
        self._toast(f"Copied the {what}")

    # --- the runs page ---

    def _render_runs(self, runs) -> None:
        signature = tuple((r.id, r.state, r.duration_s) for r in runs) + (self._runs_filter,)
        if signature == self._runs_signature:
            return
        self._runs_signature = signature
        _empty(self._runs_page)

        if not runs:
            others = [
                r
                for r in self._store.planes()
                if r not in (self._plane.name, str(self._settings.repo))
            ]
            note = (
                f"Runs from {plural(len(others), 'other control plane')} are kept separately, "
                "so this page only ever judges this one."
                if others
                else "Everything launched here is recorded, with its exit code and what "
                "Ansible reported. Nothing is written until the first run."
            )
            self._runs_page.append(
                w.empty("No runs yet for this repository", note, "document-open-recent-symbolic")
            )
            return

        self._runs_page.append(
            w.page_header(
                "Runs",
                f"{plural(len(runs), 'run')} recorded for this control plane. "
                "Anything older than this console is in the Estate, read from the release log.",
                self._filter_button(),
            )
        )
        self._runs_page.append(w.recent_run_card(runs[0], self._open_run))

        section = w.Section(
            "Run history",
            folded=self._folding.is_folded(HISTORY_SECTION),
            on_fold=lambda folded: self._folding.remember(HISTORY_SECTION, folded),
        )
        section.set_child(self._history(runs))
        self._runs_page.append(section)

        taken = self._decisions.all(self._plane.name)
        if taken:
            changes = w.Section(
                "Decisions",
                folded=self._folding.is_folded(DECISIONS_SECTION),
                on_fold=lambda folded: self._folding.remember(DECISIONS_SECTION, folded),
            )
            changes.set_child(_decision_rows(taken))
            self._runs_page.append(changes)

    def _history(self, runs) -> Gtk.Widget:
        """Every run under the day it happened on, as far as the filter allows."""
        holder = w.box(spacing=16)
        kept = runs_module.apply(runs, self._runs_filter)
        if not kept:
            holder.append(
                w.label(runs_module.by_key(self._runs_filter).empty, "tint-muted", wrap=True)
            )
            return holder

        shown = kept[:RUNS_SHOWN]
        for heading_text, day_runs in _by_day(shown):
            group = Adw.PreferencesGroup(title=heading_text)
            for run in day_runs:
                group.add(
                    w.run_row(run, self._open_run, under_a_day=True, on_relaunch=self._relaunch)
                )
            holder.append(group)
        if len(kept) > len(shown):
            holder.append(
                w.label(
                    f"{plural(len(kept) - len(shown), 'older run')} not shown. Every one of "
                    f"them is in the history file, and `ordane runs -n {len(kept)}` "
                    "prints them.",
                    "tint-muted",
                    wrap=True,
                )
            )
        return holder

    def _filter_button(self) -> Gtk.Widget:
        """Four questions the history is asked, not a query builder."""
        menu = Gio.Menu()
        for one in runs_module.FILTERS:
            item = Gio.MenuItem.new(one.label, None)
            item.set_action_and_target_value("win.runs-filter", GLib.Variant.new_string(one.key))
            menu.append_item(item)
        button = Gtk.MenuButton(
            label=runs_module.by_key(self._runs_filter).label,
            menu_model=menu,
            valign=Gtk.Align.CENTER,
        )
        button.set_tooltip_text("Show only some of the runs")
        return button

    # --- launching ---

    def _open_launch(self, target) -> None:
        dialog = LaunchDialog(
            target=target,
            catalog=self._catalog,
            config=self._config,
            repo=self._settings.repo,
            on_launch=self._launch,
        )
        dialog.present(self)

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
        GLib.idle_add(self._inventories.__setitem__, name, answer)

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
            self._toast(f"{target.name} was refused by this control plane's own policy")
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
            self._toast(f"{step.target} is not a target in this {PLANE}")
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
        """The control plane's own checks, before anything reaches a host.

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
                f"{book.target} failed. This control plane declares "
                f"{book.recovery} as its recovery.",
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

    def _open_run(self, run_id: str) -> None:
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
        self._show_run(run, output, active)

    def _show_run(self, run, output: str, active) -> None:
        page = self._stack.get_page(self._runview)
        page.set_visible(True)
        page.set_title(run.name)
        self._runview.show(run, output, active)
        self._go("run")

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
        """A short sentence, and one that cannot ask for more width than there is.

        A toast's default title does not wrap, so a long message made the
        overlay request more than the window had: hundreds of warnings and a
        toast wider than what it was reporting on.
        """
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


def _decision_rows(taken) -> Gtk.Widget:
    """What was changed, as against what was run. The two are different histories."""
    group = Adw.PreferencesGroup(
        description="What was changed here, and by whom. A run is not the only thing "
        "that decides what this console will deploy."
    )
    for decision in taken[:DECISIONS_SHOWN]:
        row = Adw.ActionRow(title=decision.summary)
        row.set_title_lines(2)
        row.set_subtitle(f"{decision.actor} · {moment(decision.at)}")
        name = DECISION_ICONS.get(decision.kind, "emblem-system-symbolic")
        icon = Gtk.Image.new_from_icon_name(name)
        if decision.widened:
            icon.add_css_class("tint-warn")
            row.add_suffix(w.badge("WIDENED", "medium"))
        row.add_prefix(icon)
        group.add(row)
    if len(taken) > DECISIONS_SHOWN:
        group.add(Adw.ActionRow(title=f"and {len(taken) - DECISIONS_SHOWN} more"))
    return group


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


def breakpoint_for(window) -> Adw.Breakpoint:
    """Below this the chrome is fighting for the width the content needs.

    The rail folds away and the header gives up which control plane it is
    driving, which is what leaves the switcher room to print its labels.
    """
    condition = Adw.BreakpointCondition.parse("max-width: 1000px")
    point = Adw.Breakpoint.new(condition)
    point.add_setter(window.split, "collapsed", True)
    point.add_setter(window._plane_button, "visible", False)
    return point


def _by_day(runs) -> list[tuple[str, list]]:
    """The runs in order, split where the day changes."""
    grouped: list[tuple[str, list]] = []
    for run in runs:
        heading = day(run.started)
        if grouped and grouped[-1][0] == heading:
            grouped[-1][1].append(run)
        else:
            grouped.append((heading, [run]))
    return grouped


def _empty(container: Gtk.Box) -> None:
    child = container.get_first_child()
    while child is not None:
        container.remove(child)
        child = container.get_first_child()


def resolve_repo(raw: Path) -> Path:
    return raw.expanduser().resolve()
