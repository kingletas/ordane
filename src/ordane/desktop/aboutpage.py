"""About: what this is, what it is running on, and where everything it wrote is.

A full screen rather than a dialog, because half of it is a table of paths
somebody actually goes and looks at, and a dialog is the wrong shape for that.
"""

from __future__ import annotations

import platform
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from .. import __version__  # noqa: E402
from ..presentation.text import plural  # noqa: E402
from . import fonts  # noqa: E402
from . import widgets as w  # noqa: E402
from .glyphs import Glyph  # noqa: E402
from .menu import PROJECT  # noqa: E402

DEVELOPER = "Luis Tineo"
COPYRIGHT = "© 2026 Luis Tineo"

LEDE = (
    "A control plane for one operator. It reads a git repository, keeps your "
    "environments honest, and remembers every run."
)

PRIVACY = (
    "Ordane runs entirely on this machine. It talks to your repository and to the hosts "
    "in your inventories — nothing else. There is no account, no telemetry, and no cloud "
    "service behind it."
)

TYPESET = (
    "Built with GTK 4 and libadwaita. Typeset in Manrope and IBM Plex Mono, both bundled "
    "with the application under the SIL Open Font License."
)


class AboutPage(Gtk.Box):
    """Identity, a facts table, the things you can do with it, and the boundary."""

    def __init__(self, *, on_copy, on_guide, on_shortcuts) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_copy = on_copy
        self._on_guide = on_guide
        self._on_shortcuts = on_shortcuts
        self._body = w.box(spacing=18)
        self.append(w.scrolled(w.clamp(self._body, maximum=660)))
        self._signature: tuple | None = None

    def render(self, facts: list[tuple[str, str]]) -> None:
        signature = tuple(facts)
        if signature == self._signature:
            return
        self._signature = signature
        w.clear(self._body)

        hero = w.row(18)
        hero.set_margin_bottom(4)
        mark = Glyph("brand", 56)
        mark.add_css_class("tint-ok")
        mark.set_valign(Gtk.Align.CENTER)
        hero.append(mark)
        text = w.box(spacing=0)
        text.set_valign(Gtk.Align.CENTER)
        text.append(w.label("Ordane", "about-title"))
        lede = w.label(LEDE, "about-lede", wrap=True)
        lede.set_max_width_chars(46)
        lede.set_margin_top(5)
        text.append(lede)
        version = w.label(f"{__version__} · a prototype, and the interfaces will move", "about-ver")
        version.set_margin_top(7)
        text.append(version)
        hero.append(text)
        self._body.append(hero)

        card = w.card()
        for index, (name, value) in enumerate(facts):
            card.append(_fact_row(name, value, last=index == len(facts) - 1))
        self._body.append(card)

        buttons = w.row(8)
        buttons.append(w.button("Copy these details", "quiet", self._on_copy, small=True))
        buttons.append(w.button("User guide", "quiet", self._on_guide, small=True))
        buttons.append(w.button("Keyboard shortcuts", "quiet", self._on_shortcuts, small=True))
        buttons.append(
            w.button(
                "Report a problem",
                "quiet",
                lambda: Gtk.UriLauncher(uri=f"{PROJECT}/issues").launch(None, None, None),
                small=True,
            )
        )
        self._body.append(buttons)

        privacy = w.label(PRIVACY, "privacy", wrap=True)
        privacy.set_max_width_chars(64)
        privacy.set_margin_top(6)
        self._body.append(privacy)

        self._body.append(w.label(TYPESET, "actrow-note", wrap=True))


def runtime() -> str:
    """What is actually underneath, read rather than assumed."""
    from gi.repository import Adw

    gtk = f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"
    adw = f"{Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}.{Adw.MICRO_VERSION}"
    return f"Python {platform.python_version()} · GTK {gtk} · libadwaita {adw}"


def facts(*, repo, plane, state_dir, runs: int, history, events) -> list[tuple[str, str]]:
    """Everything the table prints, so a test can read it without a window."""
    where = fonts.directory()
    return [
        ("Version", __version__),
        ("Runtime", runtime()),
        ("Driving", str(repo)),
        ("Known as", plane.name),
        ("Read from", plane.where_from),
        ("Run history", f"{state_dir / 'runs.jsonl'} · {plural(runs, 'run')}"),
        ("Release history", str(history)),
        ("Deployment events", str(events)),
        ("Fonts", str(where) if where else "not bundled: the system's are used"),
        ("Python", sys.executable),
        # Who wrote it and under what: a licence with no copyright holder is a
        # licence nobody can act on, and the dialog this screen replaced
        # carried both for free.
        ("Written by", DEVELOPER),
        ("Copyright", COPYRIGHT),
        ("Licence", "MIT"),
        ("Source", PROJECT),
    ]


def _fact_row(name: str, value: str, last: bool) -> Gtk.Widget:
    line = w.row(14)
    line.add_css_class("obj-row")
    if last:
        line.add_css_class("last")
    key = w.label(name, "deftable-key")
    key.set_size_request(170, -1)
    line.append(key)
    said = w.selectable(w.label(value, "deftable-val", "mono", wrap=True))
    said.set_hexpand(True)
    line.append(said)
    return line
