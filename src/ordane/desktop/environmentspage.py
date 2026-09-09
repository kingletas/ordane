"""Environments: what each one is, and what the one that is waiting needs.

It is a place rather than a dialog because it is one of the things Ordane
manages. The dialog that writes the allow list is still where the writing
happens — this is where you find out that it needs doing.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from ..core import exposure  # noqa: E402
from ..insight import environments as env_module  # noqa: E402
from ..insight.verdict import Verdict  # noqa: E402
from ..presentation.text import plural  # noqa: E402
from . import widgets as w  # noqa: E402


class EnvironmentsPage(Gtk.Box):
    """One row per declared environment, with the waiting ones opened out."""

    def __init__(self, *, on_manage, on_ask, on_run_here) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_manage = on_manage
        self._on_ask = on_ask
        self._on_run_here = on_run_here
        self._body = w.box(spacing=20)
        self.append(w.scrolled(w.clamp(self._body)))
        self._signature: tuple | None = None

    def render(self, standings: list[env_module.Standing], source: str = "") -> None:
        signature = tuple(
            (one.name, one.state, one.word, one.host_count, one.when, tuple(one.tags))
            for one in standings
        )
        if signature == self._signature:
            return
        self._signature = signature
        w.clear(self._body)

        if not standings:
            self._body.append(
                w.empty(
                    "This repository declares no environments",
                    "Ordane reads them from what `make help` prints and from the "
                    "inventory directories on disk. Neither answered.",
                    "network-workgroup-symbolic",
                )
            )
            return

        self._body.append(w.verdict_band(_verdict(standings)))
        card = w.card()
        for index, standing in enumerate(standings):
            card.append(self._row(standing, last=index == len(standings) - 1))
        self._body.append(card)
        if source:
            self._body.append(
                w.label(
                    f"Read from {source.replace('`', '')}. Ordane never invents an "
                    "environment, and the "
                    "only thing it writes back is which ones this console may reach.",
                    "actrow-note",
                    wrap=True,
                )
            )

    def _row(self, standing: env_module.Standing, last: bool) -> Gtk.Widget:
        line = w.row(15)
        line.add_css_class("obj-row")
        if last:
            line.add_css_class("last")
        line.set_valign(Gtk.Align.START)

        main = w.box(spacing=2, hexpand=True)
        heading = w.row(8)
        heading.set_halign(Gtk.Align.START)
        name = w.label(standing.name, "obj-name", "mono")
        name.set_halign(Gtk.Align.START)
        heading.append(name)
        # How exposed this is, read from its own name. Nothing else in the
        # repository says whether a run against it reaches customers.
        said_about = exposure.label(standing.name)
        if said_about:
            chip = w.tag(said_about)
            chip.add_css_class("exposed-high" if said_about == "Production" else "exposed-medium")
            chip.set_tooltip_text(exposure.caution(standing.name))
            heading.append(chip)
        main.append(heading)
        main.append(w.label(_where(standing), "obj-scope", "mono", wrap=True))

        if standing.tags:
            tags = w.row(6)
            tags.set_margin_top(8)
            for text in standing.tags:
                tags.append(w.tag(text))
            main.append(tags)

        if standing.state == env_module.WAITING:
            main.append(_what_it_needs(standing, self._on_manage))
        line.append(main)

        line.append(w.pill(standing.word, _pill(standing.state)))
        if standing.ready:
            line.append(
                w.button(
                    "Ask its hosts",
                    "quiet",
                    lambda one=standing.name: self._on_ask(one),
                    small=True,
                    tooltip="Runs a ping against this environment. It changes nothing.",
                )
            )
        return line


def _pill(state: str) -> str:
    return {
        env_module.READY: "ok",
        env_module.WAITING: "wait",
        env_module.DEGRADED: "warn",
        env_module.FAILED: "fail",
    }.get(state, "mute")


def _where(standing: env_module.Standing) -> str:
    if standing.inventory:
        hosts = "" if standing.hosts is None else f"{plural(standing.hosts, 'host')} from "
        return f"{hosts}{standing.inventory}"
    if standing.reason:
        return standing.reason
    return "declared, with no inventory path recorded"


def _what_it_needs(standing: env_module.Standing, on_manage) -> Gtk.Widget:
    """Cause, consequence and the button that fixes it — never a bare complaint."""
    holder = w.box(spacing=10)
    holder.set_margin_top(8)
    if standing.usable:
        said = (
            f"{standing.name} can be reached and has not been allowed, so nothing from "
            "here may run against it. Allowing it is a decision about production, "
            "which is why it is not made for you."
        )
        button = "Allow it"
    else:
        said = (
            f"{standing.name} is declared and has no host source, so nothing can target "
            "it. Point it at an inventory file, a cloud tag query, or type the hosts in."
        )
        button = "Choose a host source"
    note = w.label(said, "step-note", wrap=True)
    note.set_max_width_chars(56)
    holder.append(note)
    go = w.button(button, "primary", on_manage, small=True)
    go.set_halign(Gtk.Align.START)
    holder.append(go)
    return holder


def _verdict(standings: list[env_module.Standing]) -> Verdict:
    """The page's own one-liner, from the same four states as everything else."""
    waiting = [one for one in standings if one.state == env_module.WAITING]
    broken = [one for one in standings if one.state in (env_module.DEGRADED, env_module.FAILED)]
    if broken:
        return Verdict(
            state=env_module.DEGRADED,
            headline=f"{plural(len(broken), 'environment')} did not match the repository.",
            note="The last run in each says which host, and what it had to change.",
        )
    if waiting:
        return Verdict(
            state=env_module.WAITING,
            headline=f"{plural(len(waiting), 'environment')} waiting on you.",
            note="Each one below says what it needs and has the button that gives it.",
        )
    return Verdict(
        state=env_module.READY,
        headline="Every environment is ready.",
        note=f"All {len(standings)} are reachable and allowed.",
    )
