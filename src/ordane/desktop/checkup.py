"""The doctor's findings, in the window rather than only in a terminal.

Somebody who opened the desktop console is not about to be told to go and run a
command to find out why nothing works.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core.doctor import FAIL, OK, WARN, Report  # noqa: E402
from . import widgets as w  # noqa: E402

ICON = {
    OK: ("emblem-ok-symbolic", "tint-ok"),
    WARN: ("dialog-warning-symbolic", "tint-warn"),
    FAIL: ("dialog-error-symbolic", "tint-bad"),
}

HEADING = {
    FAIL: "In the way",
    WARN: "Worth fixing",
    OK: "Checked, and fine",
}


class CheckupDialog(Adw.Dialog):
    """Findings grouped worst first, each with what to do about it."""

    def __init__(self, report: Report, repo) -> None:
        super().__init__(title="Check this control plane", content_width=620)
        body = w.box(spacing=18)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(18)

        banner = w.box(Gtk.Orientation.HORIZONTAL, 14)
        banner.add_css_class("verdict")
        banner.add_css_class(_tone(report))
        icon = Gtk.Image.new_from_icon_name(
            ICON[FAIL if not report.healthy else WARN if report.warnings else OK][0]
        )
        icon.set_pixel_size(32)
        icon.set_valign(Gtk.Align.CENTER)
        banner.append(icon)
        text = w.box(spacing=3, hexpand=True)
        text.set_valign(Gtk.Align.CENTER)
        text.append(w.label(report.headline, "verdict-headline", wrap=True))
        text.append(w.label(str(repo), "verdict-sub", wrap=True))
        banner.append(text)
        body.append(banner)

        for level in (FAIL, WARN, OK):
            findings = [f for f in report.findings if f.level == level]
            if not findings:
                continue
            group = Adw.PreferencesGroup(title=HEADING[level])
            for finding in findings:
                group.add(_row(finding))
            body.append(group)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(w.sheet(body))
        self.set_child(toolbar)


def _tone(report: Report) -> str:
    """The banner reads as the worst thing in the report, not as an average."""
    if not report.healthy:
        return "problem"
    return "attention" if report.warnings else "ok"


def _row(finding) -> Adw.ActionRow:
    subtitle = " · ".join(part for part in (finding.detail, finding.fix) if part)
    row = Adw.ActionRow(title=finding.title, subtitle=subtitle)
    row.set_title_lines(2)
    row.set_subtitle_lines(4)
    name, tint = ICON[finding.level]
    image = Gtk.Image.new_from_icon_name(name)
    image.add_css_class(tint)
    row.add_prefix(image)
    return row
