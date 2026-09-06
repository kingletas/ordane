"""Where the two shared stores are, filled in here rather than in a text editor.

The Estate view used to answer "how do I point this at anything?" with a
template on the clipboard and a folder to go and find. That is a dead end with
instructions attached, which is the shape this console removes everywhere else.

The token and the password are typed into a password row and written to a file
this console creates `0600`. That is a change of position and a deliberate one:
the file exists either way, and a hand-written one takes whatever the umask
gives it: commonly `0664`, which every account on the machine can read.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..insight import stores as stores_module  # noqa: E402
from . import widgets as w  # noqa: E402

PREFIX = stores_module.PREFIX

# Title, key, what it is, and whether it is a secret. The order is the order a
# person fills them in: where it is, then how to get in, then what to read.
FIELDS = (
    (
        "InfluxDB",
        (
            ("Address", f"{PREFIX}INFLUX_URL", "http://influx.example:8086", False),
            ("Token", f"{PREFIX}INFLUX_TOKEN", "", True),
            ("Organisation", f"{PREFIX}INFLUX_ORG", "estate", False),
            ("Bucket", f"{PREFIX}INFLUX_BUCKET", "runs", False),
        ),
    ),
    (
        "Neo4j",
        (
            ("Address", f"{PREFIX}NEO4J_URL", "http://neo4j.example:7474", False),
            ("User", f"{PREFIX}NEO4J_USER", "neo4j", False),
            ("Password", f"{PREFIX}NEO4J_PASSWORD", "", True),
        ),
    ),
)


class StoresDialog(Adw.Dialog):
    """One row per setting, written to a file only this account can read."""

    def __init__(self, *, on_saved=None) -> None:
        super().__init__(title="Where the shared stores are", content_width=620)
        self._on_saved = on_saved or (lambda: None)
        self._rows: dict[str, Gtk.Widget] = {}
        self._error = Adw.Banner(revealed=False)
        self._error.add_css_class("error")
        self.set_child(self._build())

    def _build(self) -> Gtk.Widget:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self._save())
        header.pack_end(save)
        toolbar.add_top_bar(header)

        body = w.box(spacing=16)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(18)
        body.append(self._error)

        held = stores_module.read_settings_file()
        path = stores_module.settings_path()
        for name, fields in FIELDS:
            group = Adw.PreferencesGroup(title=name)
            for title, key, placeholder, secret in fields:
                row = Adw.PasswordEntryRow(title=title) if secret else Adw.EntryRow(title=title)
                row.set_text(held.get(key, ""))
                if placeholder:
                    # An EntryRow has no subtitle and no placeholder in
                    # libadwaita 1.5, so the fallback goes where it can be read.
                    row.set_tooltip_text(f"Left empty, this is {placeholder}")
                self._rows[key] = row
                group.add(row)
            body.append(group)

        told = Adw.PreferencesGroup(
            description=(
                f"Written to {path}, which only this account can read. An environment "
                f"variable of the same name overrides what is here. Both stores are "
                "read-only: nothing this console does can change what is in them."
            )
        )
        body.append(told)

        # Not a warning until there is something to warn about.
        exposed = stores_module.too_open()
        if exposed:
            banner = Adw.Banner(title=exposed, revealed=True)
            banner.add_css_class("warning")
            body.append(banner)

        toolbar.set_content(w.sheet(body))
        return toolbar

    def _save(self) -> None:
        values = {key: row.get_text().strip() for key, row in self._rows.items()}
        try:
            stores_module.write_settings_file(values)
        except stores_module.SettingsError as exc:
            self._error.set_title(str(exc))
            self._error.set_revealed(True)
            return
        self.close()
        self._on_saved()
