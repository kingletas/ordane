"""Ledger: every deploy the playbook recorded, and one of them read in full.

The list on the left is each ledger's chain, then its deploys, newest first.
The pane on the right answers the questions a reviewer asks about the chosen
deploy, then shows the flow those answers were read from, with a name on
every step.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from ..insight import ledger  # noqa: E402
from ..presentation import language  # noqa: E402
from ..presentation.text import clock, day, moment, plural  # noqa: E402
from . import widgets as w  # noqa: E402

LIST_WIDTH = 320

# How many deploys each ledger draws. The terminal prints the rest.
DEPLOYS_SHOWN = 40

ANSWER_COLUMNS = 2

OUTCOME_PILL = {
    ledger.SUCCEEDED: "ok",
    ledger.BUILT_ONLY: "ok",
    ledger.FINISHED: "wait",
    ledger.RECORDS_ONLY: "mute",
    ledger.FAILED: "fail",
    ledger.STOPPED: "fail",
    ledger.UNFINISHED: "warn",
}

LEVEL_TINT = {
    language.OK: ("tint-ok", "emblem-ok-symbolic"),
    language.ATTENTION: ("tint-warn", "dialog-warning-symbolic"),
    language.PROBLEM: ("tint-bad", "dialog-error-symbolic"),
    language.UNKNOWN: ("tint-muted", "dialog-question-symbolic"),
}

CHAIN_PILL = {
    ledger.INTACT: "ok",
    ledger.BROKEN: "fail",
    ledger.EMPTY: "mute",
    ledger.MISSING: "mute",
    ledger.UNREADABLE: "warn",
}

NONE_FOUND = (
    "This control plane names no deploy ledger. Ordane reads the `audit.path` each "
    "inventory's group_vars declares, or the paths under `ledgers:` in .ordane.yml."
)


class LedgerPage(Gtk.Box):
    """The ledgers and their deploys beside the one being read."""

    def __init__(self, *, on_configure=None) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self._on_configure = on_configure
        self._books: list[ledger.Book] = []
        self._chosen: tuple[str, str, str] | None = None
        self._rows: dict[tuple[str, str, str], Gtk.Widget] = {}
        self._signature: tuple | None = None

        column = w.box(spacing=16)
        column.set_size_request(LIST_WIDTH, -1)
        self._list = w.box(spacing=16)
        column.append(self._list)
        self._list_scroller = w.scrolled(column)
        self.append(self._list_scroller)

        self._detail = w.box(spacing=20)
        self._detail.set_margin_start(4)
        self._detail.set_margin_end(4)
        scroller = w.scrolled(self._detail)
        scroller.set_hexpand(True)
        self.append(scroller)

    def render(self, books: list[ledger.Book]) -> None:
        signature = tuple(
            (b.source.path, b.chain.state, b.chain.head, len(b.chain.entries)) for b in books
        )
        if signature == self._signature:
            return
        self._signature = signature
        self._books = list(books)
        self._draw_list()
        chosen = self._resolve_choice()
        if chosen is None:
            self._draw_nothing()
        else:
            self._show(*chosen)

    def chosen(self) -> tuple[str, str, str] | None:
        return self._chosen

    # --- the list ---

    def _draw_list(self) -> None:
        w.clear(self._list)
        self._rows = {}
        if not self._books:
            self._list.append(
                w.dormant_note(NONE_FOUND, "Open .ordane.yml", self._configure)
                if self._on_configure is not None
                else w.label(NONE_FOUND, "actrow-note", wrap=True)
            )
            return
        for book in self._books:
            self._list.append(self._book(book))

    def _book(self, book: ledger.Book) -> Gtk.Widget:
        holder = w.box(spacing=8)
        word = language.chain_state(book.chain.state)
        holder.append(
            w.band(
                book.environment or "Ledger", link=w.pill(word.name, CHAIN_PILL[book.chain.state])
            )
        )
        card = w.card()
        path = w.label(str(book.source.path), "runitem-meta", "mono")
        path.set_ellipsize(1)
        path.set_tooltip_text(f"{book.source.path}\n{_origin(book.source)}")
        head = w.box(spacing=2)
        head.add_css_class("daylabel")
        head.append(path)
        if book.chain.state == ledger.BROKEN:
            head.append(
                w.label(
                    f"Breaks at line {book.chain.broken_line}: {book.chain.reason}",
                    "runitem-meta",
                    "tint-bad",
                    wrap=True,
                )
            )
        if book.source.note:
            head.append(w.label(book.source.note, "runitem-meta", "tint-warn", wrap=True))
        headline = next((t for t in book.timings if t.key == ledger.HEADLINE), None)
        if headline is not None and headline.measured:
            head.append(w.label(_headline(headline), "runitem-meta", wrap=True))
        card.append(head)

        if not book.deployments:
            card.append(_quiet(word.meaning, last=True))
            holder.append(card)
            return holder

        current_day = ""
        shown = book.deployments[:DEPLOYS_SHOWN]
        for deployment in shown:
            heading = day(deployment.started_at)
            if heading != current_day:
                current_day = heading
                card.append(_day_label(heading))
            card.append(self._item(book, deployment))
        hidden = len(book.deployments) - len(shown)
        if hidden:
            card.append(
                _quiet(
                    f"{plural(hidden, 'older deploy')} not shown. "
                    "`ordane ledger -n 1000` prints them all."
                )
            )
        last = card.get_last_child()
        if last is not None:
            last.add_css_class("last")
        holder.append(card)
        return holder

    def _item(self, book: ledger.Book, deployment: ledger.Deployment) -> Gtk.Widget:
        key = _key(book, deployment)
        outcome = language.ledger_outcome(deployment.outcome)
        line = w.box(spacing=3)
        top = w.row(8)
        top.append(w.pill("", OUTCOME_PILL.get(deployment.outcome, "mute")))
        name = w.label(deployment.release or "No release recorded", "runitem-name", "mono")
        name.set_ellipsize(3)
        name.set_hexpand(True)
        top.append(name)
        top.append(w.label(clock(deployment.started_at), "actrow-when", "num"))
        line.append(top)

        approver = deployment.approval.signer if deployment.approval else "no approval"
        meta = f"{outcome.name} · {deployment.deployer.name} · {approver}"
        said = w.label(meta, "runitem-meta")
        said.set_ellipsize(3)
        line.append(said)
        if not deployment.trusted:
            line.append(
                w.label("Recorded after the break in the chain", "runitem-meta", "tint-bad")
            )

        button = Gtk.Button(child=line)
        button.add_css_class("runitem")
        button.add_css_class("flat")
        if key == self._chosen:
            button.add_css_class("chosen")
        button.set_tooltip_text(f"Read the deploy of {deployment.release}")
        button.connect("clicked", lambda *_: self._show(book, deployment))
        w.attach_context_menu(
            button,
            [
                ("Read this deploy", lambda: self._show(book, deployment)),
                ("Copy the release id", lambda: w.copy_to_clipboard(deployment.release)),
                (
                    "Copy the command that prints it",
                    lambda: w.copy_to_clipboard(_command(deployment)),
                ),
            ],
        )
        self._rows[key] = button
        return button

    def _resolve_choice(self) -> tuple[ledger.Book, ledger.Deployment] | None:
        """The deploy that was open, if it is still there, else the newest one anywhere."""
        pairs = [(b, d) for b in self._books for d in b.deployments]
        if not pairs:
            return None
        if self._chosen is not None:
            for book, deployment in pairs:
                if _key(book, deployment) == self._chosen:
                    return book, deployment
        return max(pairs, key=lambda pair: pair[1].started_at)

    def _configure(self) -> None:
        if self._on_configure is not None:
            self._on_configure()

    # --- the deploy being read ---

    def _draw_nothing(self) -> None:
        self._chosen = None
        w.clear(self._detail)
        text = (
            "No deploy has been recorded in these ledgers yet. The first deploy the "
            "playbook runs appears here, with who ran it and who approved it."
            if self._books
            else NONE_FOUND
        )
        self._detail.append(w.label(text, "rundetail-sub", wrap=True))

    def _show(self, book: ledger.Book, deployment: ledger.Deployment) -> None:
        self._chosen = _key(book, deployment)
        for key, widget in self._rows.items():
            if key == self._chosen:
                widget.add_css_class("chosen")
            else:
                widget.remove_css_class("chosen")

        w.release_focus(self._detail)
        w.clear(self._detail)
        self._detail.append(_title(book, deployment))
        if book.chain.state == ledger.BROKEN:
            self._detail.append(
                w.notice(
                    f"This ledger's chain breaks at line {book.chain.broken_line}: "
                    f"{book.chain.reason}. {language.chain_state(ledger.BROKEN).meaning}",
                    "loud",
                )
            )
        self._detail.append(_people(deployment))
        spans = _spans(deployment)
        if spans is not None:
            self._detail.append(spans)

        self._detail.append(
            w.band("How it went", f"{plural(len(deployment.entries), 'record')}, in order")
        )
        self._detail.append(_flow(ledger.steps(deployment)))

        answers = ledger.answers(deployment, book.chain)
        self._detail.append(w.band("What the records say", "every answer is read from the ledger"))
        self._detail.append(_answers(answers))

        self._detail.append(
            w.band("How long deploys take here", f"measured from {book.environment}'s own records")
        )
        self._detail.append(_timings(book.timings))

        exact = [value for answer in answers for value in answer.exact]
        if exact:
            self._detail.append(w.band("Exact values", "select one to copy it"))
            self._detail.append(_exact(exact))


def _title(book: ledger.Book, deployment: ledger.Deployment) -> Gtk.Widget:
    holder = w.box(spacing=4)
    top = w.row(10)
    name = w.label(deployment.release or "No release recorded", "rundetail-title", "mono")
    name.set_ellipsize(3)
    name.set_hexpand(True)
    top.append(name)
    outcome = language.ledger_outcome(deployment.outcome)
    top.append(w.pill(outcome.name, OUTCOME_PILL.get(deployment.outcome, "mute")))
    holder.append(top)
    holder.append(
        w.label(
            f"{book.environment} · started {moment(deployment.started_at)}",
            "rundetail-sub",
        )
    )
    return holder


def _people(deployment: ledger.Deployment) -> Gtk.Widget:
    """The who, before anything else: each person or host that stands behind the deploy."""
    approval = deployment.approval
    verified = deployment.verified
    build = deployment.build
    figures = [
        (deployment.deployer.name, "requested it"),
        (approval.signer if approval else "Nobody on record", "approved it"),
        (str(build.get("builder")) if build and build.get("builder") else "Not built", "built it"),
        (
            verified.actor.name if verified is not None and verified.actor.known else "Not yet",
            "verified it afterwards",
        ),
    ]
    grid = Gtk.Grid(column_homogeneous=True)
    grid.add_css_class("card")
    for index, (value, caption) in enumerate(figures):
        cell = w.box(spacing=2, hexpand=True)
        cell.add_css_class("answer")
        figure = w.label(value, "obj-name")
        figure.set_ellipsize(3)
        figure.set_tooltip_text(value)
        cell.append(figure)
        cell.append(w.label(caption, "fact-label"))
        grid.attach(cell, index % 2, index // 2, 1, 1)
    return grid


def _headline(timing: ledger.Timing) -> str:
    """The span customers feel, said as a typical figure with its range."""
    if timing.samples == 1:
        return f"{timing.name} {ledger.spoken(timing.typical)}, from one deploy"
    over = f"over {plural(timing.samples, 'deploy')}"
    if timing.fastest == timing.slowest:
        return f"{timing.name} {ledger.spoken(timing.typical)} every time, {over}"
    return (
        f"{timing.name} typically {ledger.spoken(timing.typical)}"
        f" ({ledger.spoken(timing.fastest)} to {ledger.spoken(timing.slowest)}, {over})"
    )


def _spans(deployment: ledger.Deployment) -> Gtk.Widget | None:
    """This deploy's own timings, the one customers feel first."""
    spans = deployment.spans
    order = [ledger.HEADLINE, "cutover", "build", "total", "warmup", "to_verify"]
    measured = [(key, spans[key]) for key in order if key in spans]
    if not measured:
        return None
    strip = w.row(0)
    strip.add_css_class("card")
    for index, (key, seconds) in enumerate(measured):
        if index:
            strip.append(w.divider(vertical=True))
        cell = w.box(spacing=2, hexpand=True)
        cell.set_margin_top(12)
        cell.set_margin_bottom(12)
        cell.set_margin_start(14)
        cell.set_margin_end(14)
        figure = w.label(ledger.spoken(seconds), "fact-value", "num")
        if key == ledger.HEADLINE:
            figure.add_css_class("tint-warn")
        cell.append(figure)
        name = w.label(language.span_name(key), "fact-label")
        name.set_tooltip_text(language.span_meaning(key))
        cell.append(name)
        strip.append(cell)
    return strip


def _timings(timings: list[ledger.Timing]) -> Gtk.Widget:
    """What this ledger's deploys usually cost, and what it cannot time."""
    card = w.card()
    for index, timing in enumerate(timings):
        line = w.row(12)
        line.add_css_class("obj-row")
        if index == len(timings) - 1:
            line.add_css_class("last")
        text = w.box(spacing=2, hexpand=True)
        name = w.label(timing.name, "obj-name")
        name.set_tooltip_text(timing.meaning)
        text.append(name)
        if timing.measured:
            over = f"over {plural(timing.samples, 'deploy')}"
            spread = (
                over
                if timing.fastest == timing.slowest
                else f"{ledger.spoken(timing.fastest)} to {ledger.spoken(timing.slowest)}, {over}"
            )
            text.append(w.label(spread, "obj-scope"))
        else:
            text.append(w.label(timing.blocked, "obj-scope", wrap=True))
        line.append(text)
        figure = w.label(
            ledger.spoken(timing.typical) if timing.measured else "not measured",
            "obj-name" if timing.measured else "actrow-note",
        )
        figure.set_valign(Gtk.Align.CENTER)
        line.append(figure)
        card.append(line)
    return card


def _answers(answers: list[ledger.Answer]) -> Gtk.Widget:
    grid = Gtk.Grid(column_spacing=0, row_spacing=0, column_homogeneous=True)
    grid.add_css_class("card")
    for index, answer in enumerate(answers):
        cell = w.row(10)
        cell.add_css_class("answer")
        tint, icon_name = LEVEL_TINT.get(answer.level, LEVEL_TINT[language.UNKNOWN])
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.add_css_class(tint)
        icon.set_valign(Gtk.Align.START)
        cell.append(icon)
        text = w.box(spacing=2, hexpand=True)
        text.append(w.label(answer.question, "fact-label"))
        said = w.label(answer.answer, "obj-name", wrap=True)
        text.append(said)
        if answer.detail:
            text.append(w.label(answer.detail, "actrow-note", wrap=True))
        cell.append(text)
        grid.attach(cell, index % ANSWER_COLUMNS, index // ANSWER_COLUMNS, 1, 1)
    return grid


def _flow(steps: list[ledger.Step]) -> Gtk.Widget:
    """The steps as a line down the page, each with its time, its detail and its person."""
    card = w.card()
    for index, step in enumerate(steps):
        line = w.row(12)
        line.add_css_class("flow-row")
        if index == len(steps) - 1:
            line.add_css_class("last")

        marker = w.box(spacing=0)
        marker.set_size_request(14, -1)
        dot = Gtk.Box()
        dot.add_css_class("flow-dot")
        dot.add_css_class(step.level)
        dot.set_halign(Gtk.Align.CENTER)
        marker.append(dot)
        if index < len(steps) - 1:
            stem = Gtk.Box(vexpand=True)
            stem.add_css_class("flow-stem")
            stem.set_halign(Gtk.Align.CENTER)
            marker.append(stem)
        line.append(marker)

        when = w.label(clock(step.at), "actrow-when", "num")
        when.set_size_request(44, -1)
        when.set_valign(Gtk.Align.START)
        when.set_tooltip_text(step.at)
        line.append(when)

        text = w.box(spacing=2, hexpand=True)
        name = w.label(step.name, "runitem-name")
        name.set_tooltip_text(step.meaning)
        text.append(name)
        if step.detail:
            text.append(w.label(step.detail, "runitem-meta", wrap=True))
        if not step.trusted:
            text.append(w.label("After the break in the chain", "runitem-meta", "tint-bad"))
        line.append(text)

        if step.worth_naming:
            person = w.box(spacing=1)
            person.set_valign(Gtk.Align.START)
            person.append(w.label(step.role, "fact-label", xalign=1.0))
            who = w.label(step.who, "runitem-name", xalign=1.0)
            if step.someone_else:
                who.add_css_class("tint-wait")
            who.set_ellipsize(3)
            who.set_tooltip_text(step.who)
            person.append(who)
            line.append(person)
        card.append(line)
    return card


def _exact(values: list[str]) -> Gtk.Widget:
    card = w.card()
    for index, value in enumerate(dict.fromkeys(values)):
        line = w.row(8)
        line.add_css_class("actrow")
        if index == len(dict.fromkeys(values)) - 1:
            line.add_css_class("last")
        text = w.selectable(w.label(value, "runitem-meta", "mono"))
        text.set_hexpand(True)
        text.set_ellipsize(3)
        line.append(text)
        line.append(
            w.icon_button("edit-copy-symbolic", "Copy", lambda one=value: w.copy_to_clipboard(one))
        )
        card.append(line)
    return card


def _key(book: ledger.Book, deployment: ledger.Deployment) -> tuple[str, str, str]:
    return (str(book.source.path), deployment.release, deployment.started_at)


def _origin(source: ledger.Source) -> str:
    return {
        ledger.FLAG: "Named on the command line",
        ledger.CONFIG: "Named under `ledgers:` in .ordane.yml",
        ledger.INVENTORY: f"Declared as audit.path in the {source.environment} inventory",
    }.get(source.origin, "")


def _command(deployment: ledger.Deployment) -> str:
    return f"ordane ledger {deployment.release}"


def _day_label(heading: str) -> Gtk.Widget:
    line = w.row(8)
    line.add_css_class("daylabel")
    line.append(w.label(heading))
    return line


def _quiet(text: str, last: bool = False) -> Gtk.Widget:
    line = w.row(0)
    line.add_css_class("actrow")
    if last:
        line.add_css_class("last")
    line.append(w.label(text, "actrow-note", wrap=True))
    return line
