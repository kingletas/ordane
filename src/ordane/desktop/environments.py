"""The switch that answers "how do I make anything launchable?".

Before this, the only answer was to open `.ordane.yml` in an editor, and
nothing in the interface said so. The dialog lists what `make help` found, says
what each one is, and writes the one line that decides it.
"""

from __future__ import annotations

import re
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core import edit, starter  # noqa: E402
from ..core.config import CONFIG_NAME, ConfigError  # noqa: E402
from . import widgets as w  # noqa: E402
from .awsdialog import AwsInventoryDialog  # noqa: E402

BLURB = (
    "Nothing can be launched until an environment is named here. "
    f"The list lives in {CONFIG_NAME} at the root of the control plane, and this is "
    "the only part of that file this console writes."
)

# A name this console will write into a configuration file and then hand to a
# command line: letters, digits and the three separators an inventory uses.
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class EnvironmentsDialog(Adw.Dialog):
    """Turns each environment on or off, and writes the allow list once."""

    def __init__(self, *, catalog, config, repo: Path, on_saved, on_ask=None) -> None:
        super().__init__(title="Manage environments", content_width=600)
        self._catalog = catalog
        self._config = config
        self._repo = repo
        self._on_saved = on_saved
        self._on_ask = on_ask
        self._switches: dict[str, Adw.SwitchRow] = {}
        self._added: list[str] = []
        self._error = Adw.Banner(revealed=False)
        self._error.add_css_class("error")
        self._preview = w.label("", "numeric", wrap=True)
        self.set_child(self._build())
        self._refresh_preview()

    def _ask(self, environment: str) -> None:
        self.close()
        self._on_ask(environment)

    def _build(self) -> Gtk.Widget:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        self._save = Gtk.Button(label="Save")
        self._save.add_css_class("suggested-action")
        self._save.connect("clicked", self._on_save)
        header.pack_end(self._save)
        toolbar.add_top_bar(header)

        body = w.box(spacing=16)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(16)
        body.append(self._error)
        body.append(w.label(BLURB, "tint-muted", wrap=True))
        body.append(self._list())
        body.append(self._add())

        strip = w.box(spacing=4)
        strip.add_css_class("command-strip")
        strip.append(w.label(f"WILL WRITE INTO {CONFIG_NAME}", "metric-label"))
        strip.append(self._preview)
        body.append(strip)

        toolbar.set_content(w.sheet(body))
        return toolbar

    def _list(self) -> Gtk.Widget:
        group = Adw.PreferencesGroup(
            description="Turning one on lets runs from this console reach it.",
        )
        self._group = group
        if not self._catalog.environments:
            group.add(
                Adw.ActionRow(
                    title="No environments were found",
                    subtitle="Add one below, or point `environments.discover` at them.",
                )
            )
            return group

        for environment in self._catalog.environments:
            row = Adw.SwitchRow(title=environment.name)
            if not environment.usable:
                row.set_subtitle(f"Cannot be used: {environment.reason}")
                row.set_sensitive(False)
            else:
                row.set_subtitle("Read from `make help`")
                row.set_active(environment.allowed)
                row.connect("notify::active", lambda *_: self._refresh_preview())
                if self._on_ask is not None and environment.inventory:
                    # Read-only: it asks the hosts whether they answer and
                    # changes nothing. Anything that changes one is a target.
                    ask = Gtk.Button(label="Check hosts", valign=Gtk.Align.CENTER)
                    ask.set_tooltip_text(
                        f"Ask the hosts in {environment.name} whether they answer. "
                        "It changes nothing."
                    )
                    ask.connect("clicked", lambda _b, e=environment.name: self._ask(e))
                    row.add_suffix(ask)
            self._switches[environment.name] = row
            group.add(row)
        return group

    def _add(self) -> Gtk.Widget:
        """A name for an environment nothing on disk announced.

        An inventory can live where this console does not look, and an environment need
        not be a directory at all. This writes the name under `environments.names`, read
        back alongside whatever discovery found.
        """
        group = Adw.PreferencesGroup(
            title="Add one",
            description="For an environment this console did not find on its own.",
        )
        self._new = Gtk.Entry(valign=Gtk.Align.CENTER, hexpand=True, width_chars=18)
        self._new.set_placeholder_text("production")
        self._new.connect("activate", lambda *_: self._on_add())
        row = Adw.ActionRow(
            title="Name",
            subtitle="Letters, digits, dot, dash and underscore.",
        )
        row.add_suffix(self._new)
        button = Gtk.Button(label="Add", valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda *_: self._on_add())
        row.add_suffix(button)
        row.set_activatable_widget(self._new)
        group.add(row)

        # An environment whose hosts are decided by EC2 rather than by a file.
        # It is still just an inventory: what gets written is the configuration
        # Ansible's own plugin reads, and this console never talks to AWS.
        cloud = Adw.ActionRow(
            title="From EC2",
            subtitle="Hosts asked of AWS each time, grouped by a tag.",
            activatable=True,
        )
        cloud.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        cloud.connect("activated", lambda *_: self._build_from_aws())
        group.add(cloud)
        return group

    def _build_from_aws(self) -> None:
        AwsInventoryDialog(repo=self._repo, on_written=self._aws_written).present(self)

    def _aws_written(self, name: str, written) -> None:
        """The file exists; the environment still has to be allowed to run."""
        if name not in self._switches:
            self._add_named(name, "Built from EC2")
        else:
            self._switches[name].set_active(True)
        self._refresh_preview()

    def _on_add(self) -> None:
        name = self._new.get_text().strip()
        if not NAME.match(name):
            self._fail(f"“{name}” is not a name this console will write.")
            return
        if name in self._switches:
            self._fail(f"“{name}” is already listed.")
            return
        self._new.set_text("")
        self._add_named(name, "Added here, not found on disk")
        self._refresh_preview()

    def _add_named(self, name: str, why: str) -> None:
        """One row, switched on, however the environment came to exist."""
        self._added.append(name)
        row = Adw.SwitchRow(title=name, subtitle=why)
        row.set_active(True)
        row.connect("notify::active", lambda *_: self._refresh_preview())
        self._switches[name] = row
        self._group.add(row)

    def _fail(self, message: str) -> None:
        self._error.set_title(message)
        self._error.set_revealed(True)

    def _chosen(self) -> list[str]:
        return [name for name, row in self._switches.items() if row.get_active()]

    def _refresh_preview(self) -> None:
        lines = [f"allow: {edit.render(self._chosen())}"]
        if self._added:
            lines.append(f"names: {edit.render(self._declared())}")
        self._preview.set_text("\n".join(lines))

    def _declared(self) -> list[str]:
        """Names this file has to state outright, because nothing finds them."""
        already = [e.name for e in self._catalog.environments if not e.synthetic]
        return (
            [*self._config.environment_names, *self._added]
            if self._added
            else [name for name in self._config.environment_names if name not in already]
        )

    def _on_save(self, _button) -> None:
        self._error.set_revealed(False)
        try:
            # A repository with no configuration yet gets a written one rather
            # than a two-line stub: this is the first file it will ever read.
            if not (self._repo / CONFIG_NAME).is_file():
                starter.write(self._repo, self._catalog)
            if self._added:
                edit.write(self._repo, self._declared(), key="names")
            edit.write(self._repo, self._chosen())
        except (ConfigError, OSError, starter.StarterExists) as exc:
            self._error.set_title(str(exc))
            self._error.set_revealed(True)
            return
        self.close()
        self._on_saved(self._chosen())
