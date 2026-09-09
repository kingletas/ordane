"""The application object: one window, one stylesheet, one repository."""

from __future__ import annotations

from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path

from .fonts import teach_fontconfig

# Before the first GTK import: fontconfig reads its configuration once, and a
# window that has already asked for Manrope will not be given it afterwards.
teach_fontconfig()

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import tokens  # noqa: E402
from .app_id import APP_ID  # noqa: E402
from .window import ConsoleWindow  # noqa: E402


@dataclass(frozen=True)
class Settings:
    """Where this window reads and writes.

    The release history is held as a repository-relative name rather than a
    resolved path, so opening a second control plane cannot leave the new
    window reading the old one's history.
    """

    repo: Path
    state_dir: Path
    events_path: Path
    history: str = "docs/dora/history.csv"
    page: str = "overview"

    @property
    def history_path(self) -> Path:
        return self.repo / self.history

    def for_repo(self, repo: Path) -> Settings:
        return replace(self, repo=repo, page="overview")


class ConsoleApplication(Adw.Application):
    def __init__(self, settings: Settings) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self._settings = settings
        self._provider: Gtk.CssProvider | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        # The icon `make install` puts in the user icon theme, so a running
        # window and its launcher entry show the same thing.
        Gtk.Window.set_default_icon_name(APP_ID)
        self._load_styles()
        # The palette is written into the stylesheet rather than derived from
        # libadwaita's, so a scheme change has to rewrite it.
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self._load_styles())

    def do_activate(self) -> None:
        window = self.get_active_window() or ConsoleWindow(self, self._settings)
        window.present()

    def _load_styles(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        scheme = tokens.DARK if Adw.StyleManager.get_default().get_dark() else tokens.LIGHT
        if self._provider is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self._provider)
        provider = Gtk.CssProvider()
        provider.load_from_string(stylesheet(scheme))
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._provider = provider


def stylesheet(scheme: str) -> str:
    """The palette for one scheme, then the rules that read it by name."""
    css = resources.files("ordane.desktop.assets").joinpath("app.css").read_text(encoding="utf-8")
    return f"{tokens.definitions(scheme)}\n\n{css}"


def run(settings: Settings, argv: list[str] | None = None) -> int:
    return ConsoleApplication(settings).run(argv or [])
