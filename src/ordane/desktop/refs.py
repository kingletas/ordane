"""Choosing which ref of a control plane runs, and cloning one to begin with.

**A ref is not a view of the work, it is the work.** The Makefile, the
playbooks, the inventory and `.ordane.yml` all come from the tree at the
checked-out ref, so a branch can widen the list of environments this console
will launch against, and switching to one is a decision about production
rather than about which files are on screen. Nothing here does it quietly.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core import source  # noqa: E402
from . import widgets as w  # noqa: E402

KIND_WORDS = {"branch": "branch", "remote": "on the remote", "tag": "tag"}


class RefsDialog(Adw.Dialog):
    """Every branch and tag, and what choosing one would mean."""

    def __init__(self, *, repo: Path, allowed: list[str], busy: str, on_switched) -> None:
        super().__init__(title="Choose what runs", content_width=680, content_height=620)
        self._repo = repo
        self._allowed = sorted(allowed)
        self._busy = busy
        self._on_switched = on_switched

        self._notice = Adw.Banner(revealed=False)
        self._list = w.box(spacing=18)

        page = w.box(spacing=16)
        page.set_margin_top(8)
        for side in ("bottom", "start", "end"):
            getattr(page, f"set_margin_{side}")(16)
        page.append(self._warning())
        if busy:
            page.append(
                w.notice(
                    f"{busy} is running out of this checkout. Nothing switches until it ends.",
                    "loud",
                )
            )
        page.append(self._list)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        fetch = Gtk.Button(label="Fetch")
        fetch.set_tooltip_text("Ask the remote what it has. Nothing checked out changes")
        fetch.connect("clicked", lambda *_: self._fetch())
        header.pack_end(fetch)
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self._notice)
        toolbar.set_content(w.sheet(page))
        self.set_child(toolbar)
        self._reload()

    def _warning(self) -> Gtk.Widget:
        """Said once, at the top, because it is the whole reason this is careful."""
        allowed = ", ".join(self._allowed) or "nothing yet"
        return w.notice(
            "A ref brings its own Makefile, playbooks, inventory and configuration: "
            f"including which environments may be launched against. On this one: {allowed}. "
            "A different ref may allow more.",
            "quiet",
        )

    def _reload(self) -> None:
        child = self._list.get_first_child()
        while child is not None:
            self._list.remove(child)
            child = self._list.get_first_child()

        found = source.refs(self._repo)
        if not found:
            self._list.append(
                w.empty(
                    "Not a git checkout",
                    "This control plane is a folder rather than a clone, so there is no "
                    "ref to choose. Open it from a git URL to get one.",
                    "folder-symbolic",
                )
            )
            return
        for kind, title in (
            ("branch", "Here"),
            ("remote", "On the remote"),
            ("tag", "Tags"),
        ):
            of_kind = [ref for ref in found if ref.kind == kind]
            if not of_kind:
                continue
            group = Adw.PreferencesGroup(title=title)
            for ref in of_kind:
                group.add(self._row(ref))
            self._list.append(group)

    def _row(self, ref) -> Adw.ActionRow:
        row = Adw.ActionRow(title=ref.name, subtitle=f"{ref.when} · {ref.commit} · {ref.subject}")
        row.set_subtitle_lines(2)
        if ref.current:
            row.add_suffix(w.badge("ON THIS", "ok"))
            return row
        button = Gtk.Button(label="Use this", valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda _b, name=ref.name: self._switch(name))
        if self._busy:
            button.set_sensitive(False)
            button.set_tooltip_text(f"{self._busy} is running out of this checkout")
        row.add_suffix(button)
        return row

    def _fetch(self) -> None:
        self._say(source.fetch(self._repo))
        self._reload()

    def _switch(self, name: str) -> None:
        if self._busy:
            self._say(
                source.Outcome(
                    False,
                    f"{self._busy} is running out of this checkout.",
                    "Switching would change the playbooks under it.",
                )
            )
            return
        done = source.switch(self._repo, name)
        self._say(done)
        self._reload()
        if done.ok:
            self._on_switched(name)

    def _say(self, done) -> None:
        self._notice.set_title(done.message if done.failed else done.message)
        self._notice.remove_css_class("error")
        if done.failed:
            self._notice.add_css_class("error")
            if done.detail:
                self._notice.set_title(f"{done.message} {done.detail}")
        self._notice.set_revealed(True)


class CloneDialog(Adw.Dialog):
    """A URL, a folder, and nothing that asks for a password."""

    def __init__(self, *, parent: Path, on_cloned) -> None:
        super().__init__(title="Open from a git URL", content_width=620)
        self._parent = parent
        self._on_cloned = on_cloned

        self._url = Adw.EntryRow(title="Repository URL")
        self._folder = Adw.EntryRow(title="Clone into (a folder name)")
        self._url.connect("changed", lambda *_: self._suggest())
        self._notice = Adw.Banner(revealed=False)

        group = Adw.PreferencesGroup(
            description=(
                "Cloned with the credentials git already has: your ssh agent or credential "
                "helper. This console never asks for a password and never stores one."
            )
        )
        group.add(self._url)
        group.add(self._folder)

        page = w.box(spacing=16)
        page.set_margin_top(8)
        for side in ("bottom", "start", "end"):
            getattr(page, f"set_margin_{side}")(16)
        page.append(group)
        page.append(w.label(f"Into {parent}", "metric-detail", wrap=True))

        self._clone = Gtk.Button(label="Clone")
        self._clone.add_css_class("suggested-action")
        self._clone.connect("clicked", lambda *_: self._go())
        header = Adw.HeaderBar()
        header.pack_end(self._clone)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self._notice)
        toolbar.set_content(w.sheet(page))
        self.set_child(toolbar)

    def _suggest(self) -> None:
        if not self._folder.get_text():
            self._folder.set_text(source.folder_for(self._url.get_text()))

    def _go(self) -> None:
        url = self._url.get_text().strip()
        allowed = source.usable_url(url)
        if allowed.failed:
            self._say(allowed)
            return
        self._clone.set_sensitive(False)
        self._say(source.Outcome(True, "Cloning…"))
        done = source.clone(url, self._parent, self._folder.get_text().strip())
        self._clone.set_sensitive(True)
        if done.failed:
            self._say(done)
            return
        self.close()
        self._on_cloned(Path(done.detail))

    def _say(self, done) -> None:
        self._notice.remove_css_class("error")
        title = done.message
        if done.failed:
            self._notice.add_css_class("error")
            title = f"{done.message} {done.detail}".strip()
        self._notice.set_title(title)
        self._notice.set_revealed(True)
