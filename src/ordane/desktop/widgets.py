"""The pieces the pages are assembled from."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from ..insight.health import ATTENTION, OK, PROBLEM, REMEDY_LABELS, UNKNOWN  # noqa: E402
from ..insight.metrics import Measure, Slo  # noqa: E402
from ..presentation import language  # noqa: E402
from ..presentation.text import clock, moment, took  # noqa: E402
from ..record.store import Run  # noqa: E402
from .chart import Sparkline  # noqa: E402

VERDICT_ICON = {
    OK: "emblem-ok-symbolic",
    ATTENTION: "dialog-warning-symbolic",
    PROBLEM: "dialog-error-symbolic",
    UNKNOWN: "dialog-question-symbolic",
}

VERDICT_TINT = {
    OK: "tint-ok",
    ATTENTION: "tint-warn",
    PROBLEM: "tint-bad",
    UNKNOWN: "tint-muted",
}


def notice(text: str, level: str = "quiet", action: tuple[str, str] | None = None) -> Gtk.Widget:
    """A standing fact reads quietly; only a real fault is allowed to shout.

    A notice about something a person can change carries the button that changes
    it, rather than naming a file and leaving them to find it.
    """
    bar = box(Gtk.Orientation.HORIZONTAL, 10)
    bar.add_css_class("notice")
    bar.add_css_class(level)
    icon = Gtk.Image.new_from_icon_name(
        "dialog-error-symbolic" if level == "loud" else "changes-prevent-symbolic"
    )
    icon.set_valign(Gtk.Align.CENTER)
    bar.append(icon)
    message = label(text, wrap=True)
    message.set_hexpand(True)
    bar.append(message)
    if action is not None:
        text_label, action_name = action
        button = Gtk.Button(label=text_label, valign=Gtk.Align.CENTER)
        button.add_css_class("pill")
        button.set_action_name(action_name)
        bar.append(button)
    return bar


STATE_BADGE = {
    "succeeded": ("ok", "emblem-ok-symbolic"),
    "failed": ("high", "dialog-error-symbolic"),
    "error": ("high", "dialog-error-symbolic"),
    "cancelled": ("medium", "process-stop-symbolic"),
    "running": ("running", "content-loading-symbolic"),
}


def label(text: str, *classes: str, xalign: float = 0.0, wrap: bool = False) -> Gtk.Label:
    """A label with optional CSS classes; an empty one is dropped rather than
    passed to GTK, which refuses it with a critical and no context."""
    widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap, wrap_mode=2, selectable=False)
    for name in classes:
        if name:
            widget.add_css_class(name)
    return widget


def box(orientation=Gtk.Orientation.VERTICAL, spacing: int = 0, **kwargs) -> Gtk.Box:
    return Gtk.Box(orientation=orientation, spacing=spacing, **kwargs)


def heading(text: str) -> Gtk.Label:
    widget = label(text)
    widget.add_css_class("heading")
    widget.set_margin_top(6)
    return widget


def badge(text: str, kind: str) -> Gtk.Label:
    widget = label(text.upper(), "badge", kind)
    widget.set_valign(Gtk.Align.CENTER)
    return widget


def state_badge(state: str) -> Gtk.Label:
    """A run's outcome in the word a person would use for it."""
    kind, _ = STATE_BADGE.get(state, ("", "dialog-question-symbolic"))
    widget = badge(language.state_name(state), kind)
    widget.set_tooltip_text(language.state_meaning(state))
    return widget


def danger_chip(level: str) -> Gtk.Widget | None:
    """What this target does to the estate, in words, or nothing when it does none.

    Sentence case rather than the badge's capitals: a short word in capitals
    reads as a label, and a phrase in capitals reads as shouting.
    """
    text = language.danger_badge(level)
    if not text:
        return None
    chip = label(text, "chip", level)
    chip.set_valign(Gtk.Align.CENTER)
    chip.set_tooltip_text(language.danger_note(level))
    return chip


def keycap(text: str) -> Gtk.Label:
    """One accelerator, drawn as the key it is printed on."""
    widget = label(text, "keycap")
    widget.set_valign(Gtk.Align.CENTER)
    return widget


def metric_card(measure: Measure) -> Gtk.Widget:
    """One delivery measure, in one shape whether or not it has a value.

    Label, then the value or the state, then one line of context, and for a
    measure with no source, the thing that would fill it rather than the bare
    word `no data`.
    """
    card = box(spacing=3)
    card.add_css_class("metric-card")
    if not measure.has_data:
        card.add_css_class("nodata")
    card.set_tooltip_text(language.measure_meaning(measure.key) or measure.label)
    card.append(label(language.measure_name(measure.key, measure.label).upper(), "metric-label"))

    if not measure.has_data:
        card.append(label("Setup needed", "metric-value", "absent"))
        needs = language.measure_needs(measure.key) or measure.blocked
        card.append(label(needs, "metric-detail", wrap=True))
        return card

    card.append(label(measure.value, "metric-value", "numeric"))
    card.append(label(measure.detail, "metric-detail", wrap=True))
    if measure.trend is not None:
        card.append(_trend_line(measure.trend))
    return card


def _trend_line(trend) -> Gtk.Widget:
    """How this period compares, drawn only where the sample was big enough."""
    row = box(Gtk.Orientation.HORIZONTAL, 6)
    row.set_margin_top(2)
    if trend.rose is not None:
        # The arrow says what the number did; the colour says whether that is
        # good news. A lead time that rose points up and is amber.
        arrow = Gtk.Image.new_from_icon_name("go-up-symbolic" if trend.rose else "go-down-symbolic")
        if trend.better is not None:
            arrow.add_css_class("tint-ok" if trend.better else "tint-warn")
        arrow.set_valign(Gtk.Align.CENTER)
        row.append(arrow)
    text = label(trend.text, "metric-trend", wrap=True)
    if trend.better is not None:
        text.add_css_class("tint-ok" if trend.better else "tint-warn")
    row.append(text)
    return row


def dot(kind: str) -> Gtk.Widget:
    """A status dot, which is what a person scans a list of environments for."""
    marker = label("●", "status-dot", kind)
    marker.set_valign(Gtk.Align.CENTER)
    return marker


def status_card(health, on_remedy) -> Gtk.Widget:
    """The one thing to read first: the state, what caused it, what it costs,
    and the buttons that do something about it."""
    card = box(spacing=6)
    card.add_css_class("status-card")
    card.add_css_class(health.level)

    top = box(Gtk.Orientation.HORIZONTAL, 10)
    top.append(dot(_DOT[health.level]))
    word = label(health.status, "status-word")
    top.append(word)
    card.append(top)

    if health.cause:
        card.append(label(health.cause, "status-cause", wrap=True))
    if health.impact:
        card.append(label(health.impact, "status-impact", wrap=True))
    if not health.cause and not health.impact:
        card.append(label(health.headline, "status-impact", wrap=True))

    buttons = _remedies(health, on_remedy)
    if buttons is not None:
        card.append(buttons)
    return card


_DOT = {OK: "ok", ATTENTION: "warn", PROBLEM: "bad", UNKNOWN: "muted"}


def _remedies(health, on_remedy) -> Gtk.Widget | None:
    """One button per distinct remedy the concerns name, most severe first."""
    seen: list[str] = []
    for concern in health.problems + health.attention + health.unknowns:
        if concern.remedy and concern.remedy not in seen:
            seen.append(concern.remedy)
    if not seen:
        return None
    row = box(Gtk.Orientation.HORIZONTAL, 8)
    row.set_margin_top(6)
    for index, remedy in enumerate(seen[:2]):
        button = Gtk.Button(label=REMEDY_LABELS[remedy])
        button.add_css_class("pill")
        if index == 0:
            button.add_css_class("suggested-action")
        button.connect("clicked", lambda _b, name=remedy: on_remedy(name))
        row.append(button)
    return row


def environment_card(catalog, on_manage) -> Gtk.Widget:
    """Which environments there are and whether each can be reached, in one glance."""
    card = box(spacing=6)
    card.add_css_class("metric-card")

    top = box(Gtk.Orientation.HORIZONTAL, 8)
    top.append(label("ENVIRONMENTS", "metric-label"))
    count = label(
        f"{len(catalog.launchable_environments)} of {len(catalog.environments)} launchable",
        "metric-label",
        xalign=1.0,
    )
    count.set_hexpand(True)
    top.append(count)
    card.append(top)

    for environment in catalog.environments:
        card.append(_environment_row(environment))
    if not catalog.environments:
        card.append(label("`make help` printed none", "metric-detail", wrap=True))

    # Secondary, and it says `all`: the primary version of this action is on
    # the status card beside it, and two identical buttons read as two actions.
    manage = Gtk.Button(label="Manage all…")
    manage.set_margin_top(8)
    manage.set_tooltip_text("Say which environments this console may reach")
    manage.connect("clicked", lambda *_: on_manage())
    card.append(manage)
    return card


def _environment_row(environment) -> Gtk.Widget:
    row = box(Gtk.Orientation.HORIZONTAL, 8)
    if not environment.usable:
        kind, state = "warn", environment.reason or "cannot be used"
    elif not environment.allowed:
        kind, state = "muted", "not chosen"
    else:
        kind, state = "ok", "ready"
    row.append(dot(kind))
    name = label(environment.name)
    name.set_hexpand(True)
    row.append(name)
    tint = {"warn": "tint-warn", "muted": "tint-muted"}.get(kind, "")
    row.append(label(state, "environment-state", tint, xalign=1.0))
    return row


def slo_row(slo: Slo) -> Adw.ActionRow:
    """One objective, with a bar only where there is something to draw."""
    row = Adw.ActionRow(title=slo.label, subtitle=f"{slo.target} over {slo.window}")

    if slo.has_data:
        bar = Gtk.ProgressBar(fraction=min((slo.attained or 0) / 100.0, 1.0))
        bar.add_css_class("slo-bar")
        bar.add_css_class("ok" if slo.status == "ok" else "breach")
        bar.set_valign(Gtk.Align.CENTER)
        bar.set_size_request(120, -1)
        row.add_suffix(bar)
        value = label(slo.value, "numeric")
        value.add_css_class("title-4")
        value.add_css_class("tint-ok" if slo.status == "ok" else "tint-bad")
        value.set_valign(Gtk.Align.CENTER)
        row.add_suffix(value)
    else:
        row.set_subtitle(f"{slo.target} over {slo.window} · {slo.blocked}")
        row.set_subtitle_lines(2)
        row.add_suffix(label("Setup needed", "tint-warn"))
    return row


def release_focus(container: Gtk.Widget) -> None:
    """Takes focus off anything inside, before the inside is destroyed.

    GTK's focus fixup walks a widget that is already being disposed, so a
    selectable label caught mid-teardown is a stream of criticals. Clearing the
    focus first is what lets these labels be selectable at all.
    """
    root = container.get_root()
    if root is None:
        return
    focused = root.get_focus()
    while focused is not None:
        if focused is container:
            root.set_focus(None)
            return
        focused = focused.get_parent()


def selectable(widget: Gtk.Label) -> Gtk.Label:
    """A value a person may want to take away with them, rather than retype.

    Safe only where whatever destroys the widget calls `release_focus` first.
    """
    widget.set_selectable(True)
    # Selecting it should not also make it a tab stop: the run view is read,
    # not filled in.
    widget.set_can_focus(True)
    widget.set_focus_on_click(True)
    return widget


def copy_to_clipboard(text: str) -> None:
    display = Gdk.Display.get_default()
    if display is not None:
        display.get_clipboard().set(text)


def attach_context_menu(widget: Gtk.Widget, entries: list[tuple[str, object]]) -> None:
    """A right-click menu on a row, because a row that only responds to a left click
    is hiding half of what it can do."""
    group = Gio.SimpleActionGroup()
    model = Gio.Menu()
    for index, (text, callback) in enumerate(entries):
        action = Gio.SimpleAction.new(f"item{index}", None)
        action.connect("activate", lambda *_a, run=callback: run())
        group.add_action(action)
        model.append(text, f"row.item{index}")
    widget.insert_action_group("row", group)

    popover = Gtk.PopoverMenu.new_from_model(model)
    popover.set_parent(widget)
    popover.set_has_arrow(False)
    popover.set_halign(Gtk.Align.START)
    gesture = Gtk.GestureClick(button=3)
    gesture.connect("pressed", lambda _g, _n, x, y: _popup(popover, x, y))
    widget.add_controller(gesture)
    # A popover parented to a row is not one of its children, so removing the
    # row leaves it attached to a widget on its way out. Every page here is
    # rebuilt on refresh, so this is every few seconds rather than once.
    widget.connect("notify::parent", lambda w, _p: _detach(w, popover))


def _detach(widget: Gtk.Widget, popover: Gtk.Popover) -> None:
    if widget.get_parent() is None and popover.get_parent() is not None:
        popover.unparent()


def _popup(popover: Gtk.PopoverMenu, x: float, y: float) -> None:
    rectangle = Gdk.Rectangle()
    rectangle.x, rectangle.y, rectangle.width, rectangle.height = int(x), int(y), 1, 1
    popover.set_pointing_to(rectangle)
    popover.popup()


def run_row(run: Run, on_open, under_a_day: bool = False, on_relaunch=None) -> Adw.ActionRow:
    """One recorded run, showing what Ansible reported rather than just a state.

    Under a day heading the date is already known, so the row shows the time.
    """
    when = clock(run.started) if under_a_day else moment(run.started)
    # A run of the control plane's own checks reaches no environment, so the
    # subtitle is joined from what there is rather than around a blank.
    subtitle = " · ".join(part for part in (run.environment, when) if part)
    headline = run.result.headline
    if headline:
        subtitle = f"{subtitle} · {headline}"
    elif run.exit_code not in (None, 0):
        subtitle = f"{subtitle} · exit {run.exit_code}"

    row = Adw.ActionRow(title=run.name, subtitle=subtitle, activatable=True)
    row.add_prefix(state_icon(run.state))
    if run.duration_s:
        row.add_suffix(label(took(run.duration_s), "tint-muted", "numeric"))
    row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
    row.connect("activated", lambda *_: on_open(run.id))
    row.set_tooltip_text(f"{language.state_meaning(run.state)}\nStarted {run.started}")
    entries = [("Open this run", lambda: on_open(run.id))]
    if on_relaunch is not None and run.state != "running":
        entries.append(("Run it again", lambda: on_relaunch(run.id, False)))
    entries += [
        ("Copy the command", lambda: copy_to_clipboard(run.command)),
        ("Copy the run id", lambda: copy_to_clipboard(run.id)),
    ]
    attach_context_menu(row, entries)
    return row


def state_icon(state: str) -> Gtk.Image:
    kind, icon = STATE_BADGE.get(state, ("", "dialog-question-symbolic"))
    image = Gtk.Image.new_from_icon_name(icon)
    if kind == "ok":
        image.add_css_class("tint-ok")
    elif kind == "high":
        image.add_css_class("tint-bad")
    elif kind == "medium":
        image.add_css_class("tint-warn")
    elif kind == "running":
        image.add_css_class("accent")
    return image


def recent_run_card(run: Run, on_open) -> Gtk.Widget:
    """The last run, given room: what it was, where, how it went, how long.

    The question a person opens this page with is almost always about the last
    thing that ran, and it was the first row of a list of sixty.
    """
    holder = box(spacing=6)
    holder.append(label("MOST RECENT", "metric-label"))
    card = box(Gtk.Orientation.HORIZONTAL, 14)
    card.add_css_class("metric-card")
    card.add_css_class("recent-run")
    holder.append(card)

    icon = state_icon(run.state)
    icon.set_pixel_size(28)
    icon.set_valign(Gtk.Align.START)
    card.append(icon)

    text = box(spacing=3, hexpand=True)
    title = box(Gtk.Orientation.HORIZONTAL, 10)
    name = label(run.name)
    name.add_css_class("connection-name")
    title.append(name)
    title.append(state_badge(run.state))
    text.append(title)
    text.append(label(f"{run.environment} · {moment(run.started)}", "metric-detail"))
    headline = run.result.headline or language.state_meaning(run.state)
    if headline:
        text.append(label(headline, "metric-detail", wrap=True))
    card.append(text)

    right = box(spacing=3)
    right.set_valign(Gtk.Align.CENTER)
    right.append(label(took(run.duration_s) or "—", "numeric", xalign=1.0))
    card.append(right)
    card.append(Gtk.Image.new_from_icon_name("go-next-symbolic"))

    click = Gtk.GestureClick()
    click.connect("released", lambda *_: on_open(run.id))
    card.add_controller(click)
    card.set_tooltip_text(f"Open {run.name}")
    return holder


def empty(
    title: str, description: str, icon: str = "dialog-information-symbolic"
) -> Adw.StatusPage:
    page = Adw.StatusPage(title=title, description=description, icon_name=icon)
    page.set_vexpand(True)
    return page


# Wide enough for two cards side by side and no wider: content that runs the
# width of a large monitor is content nobody reads the right-hand end of.
CONTENT_WIDTH = 1150


class Section(Gtk.Box):
    """A heading that folds away what is under it, and remembers that it was folded.

    A page that opens with sixty rows on it is one somebody scrolls past to
    reach the thing they came for; whether they want them is their decision
    rather than a layout constant.
    """

    def __init__(self, title: str, *, folded: bool = False, on_fold=None, beside=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._on_fold = on_fold or (lambda _folded: None)

        line = box(Gtk.Orientation.HORIZONTAL, 8)
        self._chevron = Gtk.Image.new_from_icon_name(
            "pan-end-symbolic" if folded else "pan-down-symbolic"
        )
        line.append(self._chevron)
        line.append(label(title, "heading"))

        self._toggle = Gtk.Button(child=line, has_frame=False)
        self._toggle.add_css_class("flat")
        self._toggle.add_css_class("section-toggle")
        self._toggle.set_hexpand(True)
        self._toggle.set_halign(Gtk.Align.START)
        # `fold(True)` folds. Revealed means not folded, so the state to ask
        # for is the current reveal: `not` here made the click a no-op both
        # ways, and a test that called `fold` directly never saw it.
        self._toggle.connect("clicked", lambda *_: self.fold(self._revealer.get_reveal_child()))

        head = box(Gtk.Orientation.HORIZONTAL, 10)
        head.append(self._toggle)
        if beside is not None:
            beside.set_valign(Gtk.Align.CENTER)
            head.append(beside)
        self.append(head)

        self._revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, reveal_child=not folded
        )
        self.append(self._revealer)

    def set_child(self, child: Gtk.Widget) -> None:
        self._revealer.set_child(child)

    def fold(self, folded: bool) -> None:
        self._revealer.set_reveal_child(not folded)
        self._chevron.set_from_icon_name("pan-end-symbolic" if folded else "pan-down-symbolic")
        self._toggle.set_tooltip_text("Show these again" if folded else "Fold these away")
        self._on_fold(folded)


def page_header(title: str, lede: str = "", control: Gtk.Widget | None = None) -> Gtk.Widget:
    """A view's own name, one line of context, and whatever that view is driven by."""
    holder = box(spacing=4)
    top = box(Gtk.Orientation.HORIZONTAL, 12)
    heading = label(title, "page-title")
    heading.set_hexpand(True)
    top.append(heading)
    if control is not None:
        control.set_valign(Gtk.Align.CENTER)
        top.append(control)
    holder.append(top)
    if lede:
        holder.append(label(lede, "page-lede", wrap=True))
    return holder


class PlaneButton(Gtk.Button):
    """Which control plane this window drives, in the header rather than in a rail."""

    def __init__(self, on_details) -> None:
        super().__init__(has_frame=False)
        self.add_css_class("flat")
        inside = box(Gtk.Orientation.HORIZONTAL, 8)
        inside.set_valign(Gtk.Align.CENTER)
        self._dot = dot("muted")
        inside.append(self._dot)
        lines = box()
        self._name = label("", "plane-name")
        self._name.set_ellipsize(3)
        self._state = label("", "plane-state")
        lines.append(self._name)
        lines.append(self._state)
        inside.append(lines)
        self.set_child(inside)
        self.connect("clicked", lambda *_: on_details())

    def render(self, *, repo, readable: bool, freshness: str, checkout, actor, plane) -> None:
        for kind in ("ok", "bad", "muted"):
            self._dot.remove_css_class(kind)
        self._dot.add_css_class("ok" if readable else "bad")
        self._name.set_text(plane.name)
        self._state.set_text(freshness if readable else "cannot be read")
        self.set_tooltip_text(
            f"{repo}\n{plane.where_from}\n"
            f"{checkout.summary or 'not a git checkout'}\n{actor.summary}"
        )


def clamp(child: Gtk.Widget, maximum: int = CONTENT_WIDTH) -> Adw.Clamp:
    holder = Adw.Clamp(maximum_size=maximum, tightening_threshold=700, child=child)
    holder.set_margin_top(26)
    holder.set_margin_bottom(28)
    holder.set_margin_start(24)
    holder.set_margin_end(24)
    return holder


def scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    return Gtk.ScrolledWindow(child=child, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)


# How tall a dialog is allowed to grow before its content starts scrolling.
SHEET_MAX_HEIGHT = 640


def sheet(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    """A dialog body that is as tall as its content and no taller.

    A plain scroller inside a dialog collapses to nothing, because a dialog
    sizes itself to what its child asks for and a scroller asks for nothing.
    """
    return Gtk.ScrolledWindow(
        child=child,
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        propagate_natural_height=True,
        max_content_height=SHEET_MAX_HEIGHT,
    )


def metric_card_with_series(measure: Measure, series) -> Gtk.Widget:
    """A measure card that also draws its own history."""
    card = metric_card(measure)
    if series:
        spark = Sparkline(series)
        spark.set_margin_top(6)
        card.append(spark)
        card.append(label(series.caption, "metric-detail"))
    return card
