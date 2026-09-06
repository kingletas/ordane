"""Builds an environment that asks EC2 what is in it.

What this writes is a configuration file for `amazon.aws.aws_ec2`, in a
directory named after the environment. The console does not talk to EC2 and is
not going to: Ansible's plugin already does, with the whole boto3 credential
chain behind it, and a second EC2 client in a desktop application would be a
system in front of the one that works.

So the fields here are the ones the plugin needs and nothing more. There is no
key and no secret, because a repository is the worst place either could live.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core import awsinventory  # noqa: E402
from . import widgets as w  # noqa: E402

TOLD = (
    "Needs the amazon.aws collection and boto3, and credentials from the usual "
    "chain: environment, profile, instance role, SSO. None is written here."
)


class AwsInventoryDialog(Adw.Dialog):
    """The fields the EC2 plugin needs, and a preview of what will be written."""

    def __init__(self, *, repo: Path, on_written=None) -> None:
        super().__init__(title="Build an environment from EC2", content_width=640)
        self._repo = repo
        self._on_written = on_written or (lambda _name, _path: None)
        self._error = Adw.Banner(revealed=False)
        self._error.add_css_class("error")
        self._preview = w.label("", "numeric", wrap=True)
        self.set_child(self._build())
        self._refresh()

    def _build(self) -> Gtk.Widget:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        self._write = Gtk.Button(label="Write it")
        self._write.add_css_class("suggested-action")
        self._write.connect("clicked", lambda *_: self._on_write())
        header.pack_end(self._write)
        toolbar.add_top_bar(header)

        body = w.box(spacing=16)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(18)
        body.append(self._error)

        group = Adw.PreferencesGroup(description=TOLD)
        self._name = Adw.EntryRow(title="Environment name")
        self._name.set_text("production")
        self._regions = Adw.EntryRow(title="Regions, comma separated")
        self._regions.set_text("us-east-1")
        self._group_by = Adw.EntryRow(title="Group hosts by which tag")
        self._group_by.set_text("Role")
        for row in (self._name, self._regions, self._group_by):
            row.connect("changed", lambda *_: self._refresh())
            group.add(row)
        body.append(group)

        narrowing = Adw.PreferencesGroup(
            title="Which instances",
            description="Running instances only, always. Leave the tag empty for all of them.",
        )
        self._filter_tag = Adw.EntryRow(title="Only those tagged")
        self._filter_value = Adw.EntryRow(title="with the value")
        self._filter_value.set_text("*")
        for row in (self._filter_tag, self._filter_value):
            row.connect("changed", lambda *_: self._refresh())
            narrowing.add(row)
        body.append(narrowing)

        reaching = Adw.PreferencesGroup(title="How they are reached")
        self._private = Adw.SwitchRow(
            title="Private addresses",
            subtitle="Off only when deploying to hosts from outside their VPC.",
            active=True,
        )
        self._private.connect("notify::active", lambda *_: self._refresh())
        reaching.add(self._private)
        self._profile = Adw.EntryRow(title="AWS profile, if not the default")
        self._profile.connect("changed", lambda *_: self._refresh())
        reaching.add(self._profile)
        body.append(reaching)

        shown = Adw.PreferencesGroup(title="What gets written")
        holder = w.box(spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(holder, f"set_margin_{side}")(12)
        holder.append(self._preview)
        frame = Gtk.Frame(child=holder)
        shown.add(frame)
        body.append(shown)

        toolbar.set_content(w.sheet(body))
        return toolbar

    def _spec(self) -> awsinventory.Spec:
        regions = tuple(one.strip() for one in self._regions.get_text().split(",") if one.strip())
        return awsinventory.Spec(
            regions=regions,
            group_by_tag=self._group_by.get_text().strip(),
            filter_tag=self._filter_tag.get_text().strip(),
            filter_value=self._filter_value.get_text().strip(),
            profile=self._profile.get_text().strip(),
            private_addresses=self._private.get_active(),
        )

    def _refresh(self) -> None:
        """The file itself, so nothing is written that was not read first."""
        try:
            body = awsinventory.render(self._spec())
        except awsinventory.AwsInventoryError as exc:
            self._preview.set_text(f"— {exc}")
            self._write.set_sensitive(False)
            return
        self._write.set_sensitive(True)
        where = awsinventory.path_for(self._repo, self._name.get_text().strip() or "?")
        try:
            shown = where.relative_to(self._repo)
        except ValueError:
            shown = where
        self._preview.set_text(f"{shown}\n\n{body}")

    def _on_write(self) -> None:
        name = self._name.get_text().strip()
        try:
            written = awsinventory.write(self._repo, name, self._spec())
        except awsinventory.AwsInventoryError as exc:
            self._error.set_title(str(exc))
            self._error.set_revealed(True)
            return
        self.close()
        self._on_written(name, written)
