"""Setup: the seven steps, in the order that makes each one possible.

It is a screen you reach from the card on Overview rather than a place in the
rail, because it stops existing once it is finished.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from ..insight.setup import Setup, Step  # noqa: E402
from ..insight.verdict import READY, WAITING, Verdict  # noqa: E402
from ..presentation.text import plural  # noqa: E402
from . import widgets as w  # noqa: E402


class SetupPage(Gtk.Box):
    """Done steps recede; the next one is the only one with a filled button."""

    def __init__(self, *, on_remedy) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_remedy = on_remedy
        self._body = w.box(spacing=18)
        self.append(w.scrolled(w.clamp(self._body)))
        self._signature: tuple | None = None

    def render(self, setup: Setup) -> None:
        signature = tuple((step.key, step.done, step.note) for step in setup.steps)
        if signature == self._signature:
            return
        self._signature = signature
        w.clear(self._body)
        self._body.append(w.verdict_band(_verdict(setup)))

        card = w.card()
        next_step = setup.next_step
        for index, step in enumerate(setup.steps):
            card.append(
                self._step(
                    step,
                    number=index + 1,
                    is_next=next_step is not None and step.key == next_step.key,
                    last=index == len(setup.steps) - 1,
                )
            )
        self._body.append(card)

    def _step(self, step: Step, *, number: int, is_next: bool, last: bool) -> Gtk.Widget:
        line = w.row(14)
        line.add_css_class("step")
        if step.done:
            line.add_css_class("done")
        if last:
            line.add_css_class("last")
        line.set_valign(Gtk.Align.START)

        line.append(_mark(step.done, number, is_next))

        body = w.box(spacing=3, hexpand=True)
        body.append(w.label(step.title, "step-name", wrap=True))
        note = w.label(step.note, "step-note", wrap=True)
        note.set_max_width_chars(64)
        body.append(note)
        if not step.done and step.unlocks:
            unlocks = w.label(f"Turns on {_lower(step.unlocks)}", "unlocks", wrap=True)
            unlocks.set_margin_top(3)
            body.append(unlocks)
        line.append(body)

        if not step.done and step.button:
            line.append(
                w.button(
                    step.button,
                    "primary" if is_next else "quiet",
                    lambda one=step.remedy: self._on_remedy(one),
                    small=True,
                )
            )
        return line


def _mark(done: bool, number: int, is_next: bool) -> Gtk.Widget:
    """A tick or a step number, in a ring that says which of the three it is."""
    if done:
        mark = Gtk.Image.new_from_icon_name("object-select-symbolic")
        mark.set_pixel_size(12)
    else:
        mark = w.label(str(number), "mono", xalign=0.5)
    mark.add_css_class("mark")
    mark.add_css_class("done" if done else ("next" if is_next else "step-open"))
    mark.set_valign(Gtk.Align.START)
    mark.set_halign(Gtk.Align.CENTER)
    return mark


def _verdict(setup: Setup) -> Verdict:
    if setup.complete:
        return Verdict(
            state=READY,
            headline="Setup is finished.",
            note="Everything Ordane can be told about this repository, it has been told.",
        )
    return Verdict(
        state=WAITING,
        headline=f"{plural(setup.left, 'step')} left.",
        note="Each one turns a specific thing on. You can stop after any of them and "
        "Ordane still works.",
    )


def _lower(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text
