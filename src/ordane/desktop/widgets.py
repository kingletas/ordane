"""The pieces the pages are assembled from.

Everything here follows two rules from the design. Nothing is set in capitals,
because a label in capitals is a label that has been shouted; and mono is only
ever used for a string somebody could paste into a terminal — a hostname, an
environment, an action, a ref, a path, a duration, a timestamp.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk, Pango  # noqa: E402

from ..core import exposure  # noqa: E402
from ..insight.health import ATTENTION, OK, PROBLEM, UNKNOWN  # noqa: E402
from ..insight.metrics import Measure, Slo  # noqa: E402
from ..presentation import language  # noqa: E402
from ..presentation.text import clock, moment, took  # noqa: E402
from ..record.store import Run  # noqa: E402
from .chart import Gauge, MetricBars, MetricLine  # noqa: E402

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
    UNKNOWN: "tint-wait",
}

# Wide enough for two cards side by side and no wider: content that runs the
# width of a large monitor is content nobody reads the right-hand end of.
CONTENT_WIDTH = 1080

# How tall a dialog is allowed to grow before its content starts scrolling.
SHEET_MAX_HEIGHT = 640

# The narrowest the verdict line may be asked to become. See `verdict_band`.
VERDICT_MIN_CHARS = 18

# The four states of the ramp, and the pill class that says each one.
PILL = {
    "ok": "ok",
    "wait": "wait",
    "warn": "warn",
    "fail": "fail",
    "live": "live",
    "mute": "mute",
}

STATE_BADGE = {
    "succeeded": ("ok", "emblem-ok-symbolic"),
    "failed": ("high", "dialog-error-symbolic"),
    "error": ("high", "dialog-error-symbolic"),
    "cancelled": ("medium", "process-stop-symbolic"),
    "running": ("running", "content-loading-symbolic"),
}


# --- the primitives everything else is built out of -------------------------


def label(text: str, *classes: str, xalign: float = 0.0, wrap: bool = False) -> Gtk.Label:
    """A label with optional CSS classes; an empty one is dropped rather than
    passed to GTK, which refuses it with a critical and no context."""
    widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap, wrap_mode=2, selectable=False)
    if wrap:
        # A wrapping label's natural width otherwise grows with its longest
        # unbreakable word, so a path or a hostname in a sentence makes the
        # whole page demand more room than the window has. GTK says so as
        # `reports a minimum width of N but minimum width for height is M`.
        widget.set_natural_wrap_mode(Gtk.NaturalWrapMode.NONE)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    for name in classes:
        if name:
            widget.add_css_class(name)
    return widget


def box(orientation=Gtk.Orientation.VERTICAL, spacing: int = 0, **kwargs) -> Gtk.Box:
    return Gtk.Box(orientation=orientation, spacing=spacing, **kwargs)


def row(spacing: int = 0, **kwargs) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing, **kwargs)


def spacer(vertical: bool = False) -> Gtk.Widget:
    """Pushes whatever follows it to the far end of a row, or of a column."""
    return Gtk.Box(vexpand=True) if vertical else Gtk.Box(hexpand=True)


def divider(vertical: bool = False) -> Gtk.Widget:
    line = Gtk.Box()
    line.add_css_class("divider")
    line.set_size_request(1, -1) if vertical else line.set_size_request(-1, 1)
    return line


def card(spacing: int = 0, small: bool = False) -> Gtk.Box:
    """One elevation, one radius. Hierarchy comes from size and position."""
    holder = box(spacing=spacing)
    holder.add_css_class("card")
    if small:
        holder.add_css_class("card-small")
    return holder


def button(
    text: str,
    kind: str = "quiet",
    on_click=None,
    small: bool = False,
    tooltip: str = "",
    action: str = "",
) -> Gtk.Button:
    """A button names its outcome, so it says what it will do before it does it."""
    widget = Gtk.Button(label=text, valign=Gtk.Align.CENTER)
    widget.add_css_class(kind)
    if small:
        widget.add_css_class("sm")
    if tooltip:
        widget.set_tooltip_text(tooltip)
    if action:
        widget.set_action_name(action)
    if on_click is not None:
        widget.connect("clicked", lambda *_: on_click())
    return widget


def linkish(text: str, on_click=None, action: str = "") -> Gtk.Button:
    """The quiet link at the right-hand end of a band heading."""
    widget = Gtk.Button(label=text)
    widget.add_css_class("linkish")
    widget.add_css_class("flat")
    widget.set_valign(Gtk.Align.CENTER)
    if action:
        widget.set_action_name(action)
    if on_click is not None:
        widget.connect("clicked", lambda *_: on_click())
    return widget


def icon_button(name: str, tooltip: str, on_click=None, action: str = "") -> Gtk.Button:
    widget = Gtk.Button(icon_name=name, valign=Gtk.Align.CENTER)
    widget.add_css_class("iconbtn")
    widget.set_tooltip_text(tooltip)
    if action:
        widget.set_action_name(action)
    if on_click is not None:
        widget.connect("clicked", lambda *_: on_click())
    return widget


def keycap(text: str) -> Gtk.Label:
    """One accelerator, drawn as the key it is printed on."""
    widget = label(text, "keycap")
    widget.set_valign(Gtk.Align.CENTER)
    return widget


def band(title: str, aside: str = "", link: Gtk.Widget | None = None) -> Gtk.Widget:
    """A section heading in sentence case, its context, and one link."""
    line = row(10)
    line.set_margin_bottom(2)
    heading_label = label(title, "band")
    line.append(heading_label)
    if aside:
        # Context, not content: it ellipsises rather than setting the width of
        # the page under it. A long aside on a non-wrapping label makes the
        # whole screen demand more room than the window has.
        said = label(aside, "band-aside")
        said.set_ellipsize(3)
        said.set_tooltip_text(aside)
        line.append(said)
    line.append(spacer())
    if link is not None:
        line.append(link)
    return line


def pill(text: str, kind: str = "mute") -> Gtk.Widget:
    """Outcome in a word, with the dot that carries it at a glance."""
    holder = row(6)
    holder.add_css_class("pill")
    holder.add_css_class(PILL.get(kind, "mute"))
    holder.set_valign(Gtk.Align.CENTER)
    holder.set_halign(Gtk.Align.START)
    marker = Gtk.Box()
    marker.add_css_class("dot")
    marker.set_valign(Gtk.Align.CENTER)
    holder.append(marker)
    if text:
        holder.append(label(text))
    return holder


def tag(text: str, off: bool = False) -> Gtk.Widget:
    """A short fact beside a row. It ellipsises so a row of them has a small
    minimum: at any real width they are drawn whole."""
    widget = label(text, "tag", "mono")
    if off:
        widget.add_css_class("off")
    widget.set_valign(Gtk.Align.CENTER)
    widget.set_ellipsize(3)
    return widget


def beacon(state: str = "ready") -> Gtk.Widget:
    """One per screen, maximum: the dot the verdict is read from."""
    marker = Gtk.Box()
    marker.add_css_class("beacon")
    if state and state != "ready":
        marker.add_css_class(state)
    marker.set_valign(Gtk.Align.START)
    marker.set_halign(Gtk.Align.CENTER)
    return marker


def fact(value: str, name: str, mono: bool = True) -> Gtk.Widget:
    """A value over its label, which is how three of them read as one row."""
    cell = box(spacing=1)
    figure = label(value, "fact-value", "num")
    if mono:
        figure.add_css_class("mono")
    cell.append(figure)
    cell.append(label(name, "fact-label"))
    return cell


def progress(fraction: float, style: str = "setup-bar") -> Gtk.ProgressBar:
    bar = Gtk.ProgressBar(fraction=max(0.0, min(1.0, fraction)))
    bar.add_css_class(style)
    bar.set_valign(Gtk.Align.CENTER)
    return bar


# --- the verdict, the setup card and the environment strip ------------------


def verdict_band(verdict, on_remedy=None) -> Gtk.Widget:
    """One sentence saying whether it is safe to act, then the thing in the way."""
    holder = box(spacing=0)
    line = row(13)
    line.append(beacon(verdict.state))
    headline = label(verdict.headline, "verdict-title", wrap=True)
    headline.set_max_width_chars(24)
    # A 29px label that may wrap to one character reports a minimum GTK's
    # height-for-width pass disagrees with, and says so on every layout. Pinning
    # the minimum above its longest word settles it, and the figure is well
    # under the width the content well already asks for. The natural width has
    # to grow with the text again, or the natural is below the minimum and GTK
    # complains about that instead.
    headline.set_width_chars(VERDICT_MIN_CHARS)
    headline.set_natural_wrap_mode(Gtk.NaturalWrapMode.INHERIT)
    line.append(headline)
    holder.append(line)
    if verdict.note:
        under = box(spacing=6)
        under.set_margin_start(24)
        under.set_margin_top(9)
        note = label(verdict.note, "verdict-note", wrap=True)
        note.set_max_width_chars(62)
        under.append(note)
        if verdict.actionable and on_remedy is not None:
            go = linkish(verdict.remedy_label, lambda: on_remedy(verdict.remedy))
            go.set_halign(Gtk.Align.START)
            under.append(go)
        holder.append(under)
    return holder


def environment_tile(
    *, name: str, state: str, word: str, facts: list[tuple[str, str]], fix: str = ""
) -> Gtk.Widget:
    """One environment: a status bar down its edge, its name, and three facts."""
    outer = row(0)
    outer.add_css_class("card")
    outer.add_css_class("card-small")

    bar = Gtk.Box()
    bar.add_css_class("env-bar")
    if state != "ready":
        bar.add_css_class(state)
    outer.append(bar)

    inside = box(spacing=0, hexpand=True)
    inside.add_css_class("env-tile")
    heading = row(8)
    title = label(name, "env-name", "mono")
    title.set_ellipsize(3)
    title.set_hexpand(True)
    heading.append(title)
    # What the name says about how exposed this is, where somebody reads the
    # environment rather than where they run something against it.
    said_about = exposure.label(name)
    if said_about:
        chip = tag(said_about)
        chip.add_css_class("exposed-high" if said_about == "Production" else "exposed-medium")
        heading.append(chip)
    inside.append(heading)
    said = label(word, "env-state")
    if state != "ready":
        said.add_css_class(state)
    said.set_margin_top(3)
    inside.append(said)

    strip = row(14)
    for value, caption in facts:
        strip.append(fact(value, caption))
    holder = box(spacing=9)
    holder.set_margin_top(10)
    holder.append(divider())
    holder.append(strip)
    inside.append(holder)

    if fix:
        hint = label(fix, "env-fix", wrap=True)
        hint.set_margin_top(9)
        inside.append(hint)
    outer.append(inside)
    return outer


def setup_card(*, title: str, note: str, fraction: float, counted: str, on_go) -> Gtk.Widget:
    """One card in place of five scattered `Setup needed` states. Blue, never amber."""
    outer = row(18)
    outer.add_css_class("setup-card")

    body = box(spacing=0, hexpand=True)
    body.set_valign(Gtk.Align.CENTER)
    body.append(label(title, "setup-title", wrap=True))
    said = label(note, "setup-note", wrap=True)
    said.set_max_width_chars(58)
    said.set_margin_top(4)
    body.append(said)

    bar = progress(fraction)
    bar.set_margin_top(12)
    bar.set_size_request(340, -1)
    bar.set_halign(Gtk.Align.START)
    body.append(bar)

    count = label(counted, "progress-text", "mono")
    count.set_margin_top(6)
    body.append(count)
    outer.append(body)
    outer.append(button("Continue setup", "primary", on_go))
    return outer


# --- delivery ----------------------------------------------------------------


def metric_card(measure: Measure, series=None, animate: bool = True) -> Gtk.Widget:
    """One delivery measure: its name, the figure, what it is measured over.

    A measure with no source is dormant rather than alarming — a dashed outline
    and the sentence that would turn it on, never the words `Setup needed`.
    """
    holder = card(spacing=0)
    holder.add_css_class("metric")
    holder.set_tooltip_text(language.measure_meaning(measure.key) or measure.label)
    holder.append(label(language.measure_name(measure.key, measure.label), "metric-name"))

    if not measure.has_data:
        holder.remove_css_class("card")
        holder.add_css_class("dormant")
        value = label("Not measured yet", "metric-value")
        value.set_margin_top(12)
        holder.append(value)
        needs = label(
            language.measure_needs(measure.key) or measure.blocked, "metric-detail", wrap=True
        )
        needs.set_margin_top(8)
        needs.set_max_width_chars(52)
        holder.append(needs)
        return holder

    figure = row(3)
    figure.set_margin_top(7)
    number = label(measure.figure, "metric-value")
    number.set_valign(Gtk.Align.BASELINE)
    figure.append(number)
    if measure.unit:
        unit = label(measure.unit, "metric-unit")
        unit.set_valign(Gtk.Align.BASELINE)
        figure.append(unit)
    holder.append(figure)

    basis = label(measure.detail, "metric-basis", "mono", wrap=True)
    basis.set_margin_top(5)
    holder.append(basis)

    if measure.trend is not None:
        holder.append(_trend(measure.trend))
    if series:
        holder.append(_chart_block(series, measure.key, animate))
    return holder


def _trend(trend) -> Gtk.Widget:
    """How this period compares, with an arrow that says what the number did.

    The arrow is the direction and the colour is whether that is good news: a
    lead time that rose points up and is amber.
    """
    line = row(5)
    line.set_margin_top(9)
    icon = "list-remove-symbolic"
    if trend.rose is not None:
        icon = "go-up-symbolic" if trend.rose else "go-down-symbolic"
    arrow = Gtk.Image.new_from_icon_name(icon)
    arrow.set_valign(Gtk.Align.CENTER)
    line.append(arrow)
    text = label(trend.text, "metric-trend", wrap=True)
    if trend.better is not None:
        text.add_css_class("good" if trend.better else "bad")
        arrow.add_css_class("tint-ok" if trend.better else "tint-warn")
    line.append(text)
    return line


def _chart_block(series, key: str, animate: bool) -> Gtk.Widget:
    """The chart, and the axis whose labels name the same range as the basis line."""
    holder = box(spacing=5)
    holder.set_margin_top(11)
    holder.append(divider())
    drawing = MetricBars(series) if key == "cadence" else MetricLine(series, animate=animate)
    drawing.set_margin_top(10)
    holder.append(drawing)

    axis = row(0)
    labels = series.labels
    for index, name in enumerate((labels[0], labels[len(labels) // 2], labels[-1])):
        text = label(name, "axis-label", "mono")
        if index == 1:
            text.set_hexpand(True)
            text.set_halign(Gtk.Align.CENTER)
        elif index == 2:
            text.set_halign(Gtk.Align.END)
        axis.append(text)
    holder.append(axis)
    return holder


def dormant_note(text: str, action: str, on_go) -> Gtk.Widget:
    """What two dark measures are waiting on, said once rather than twice."""
    holder = row(14)
    holder.add_css_class("dormant-note")
    said = label(text, wrap=True)
    said.set_hexpand(True)
    said.set_max_width_chars(66)
    holder.append(said)
    holder.append(button(action, "quiet", on_go, small=True))
    return holder


def objective_row(slo: Slo, last: bool = False, on_fix=None) -> Gtk.Widget:
    """Name, window, a gauge with the target marked, then what it is short of."""
    line = row(15)
    line.add_css_class("obj-row")
    if last:
        line.add_css_class("last")

    main = box(spacing=2, hexpand=True)
    main.set_valign(Gtk.Align.CENTER)
    main.append(label(slo.label, "obj-name", wrap=True))
    scope = f"{slo.window} window" if slo.has_data else slo.blocked
    main.append(label(scope, "obj-scope", "mono", wrap=True))
    line.append(main)

    gauge = box(spacing=4)
    gauge.set_size_request(132, -1)
    gauge.set_valign(Gtk.Align.CENTER)
    gauge.append(Gauge(slo.attained if slo.has_data else None, _target_of(slo)))
    figures = row(0)
    figures.append(label(slo.value or "—", "gauge-text", "mono"))
    figures.append(spacer())
    figures.append(label(f"target {slo.target}", "gauge-text", "mono"))
    gauge.append(figures)
    line.append(gauge)

    if not slo.has_data:
        line.append(pill(needs_of(slo), "wait"))
    elif slo.status == "ok":
        line.append(pill("Meeting", "ok"))
    else:
        line.append(pill("Below target", "fail"))
    if on_fix is not None and not slo.has_data:
        line.append(button("Set it up", "quiet", on_fix, small=True))
    return line


def needs_of(slo: Slo) -> str:
    """What an unmeasured objective is short of, never the words `Setup needed`."""
    blocked = (slo.blocked or "").lower()
    if "cutover" in blocked:
        return "Needs 1 cutover"
    if "probe" in blocked or "instrument" in blocked:
        return "Needs a probe"
    return "Needs a source"


def _target_of(slo: Slo) -> float:
    try:
        return float(str(slo.target).rstrip("%"))
    except ValueError:
        return 100.0


# --- tables -------------------------------------------------------------------


def table_head(columns: list[tuple[str, int]]) -> Gtk.Widget:
    line = row(14)
    line.add_css_class("table-head")
    line.set_margin_start(14)
    line.set_margin_end(14)
    line.set_margin_top(8)
    line.set_margin_bottom(8)
    for name, width in columns:
        cell = label(name)
        if width:
            cell.set_size_request(width, -1)
        else:
            cell.set_hexpand(True)
        line.append(cell)
    return line


def summary_strip(figures: list[tuple[str, str]]) -> Gtk.Widget:
    """Big numbers with a sentence under each, across the top of a page."""
    strip = row(0)
    strip.add_css_class("card")
    for index, (value, caption) in enumerate(figures):
        if index:
            strip.append(divider(vertical=True))
        cell = box(spacing=2, hexpand=True)
        cell.set_margin_top(13)
        cell.set_margin_bottom(13)
        cell.set_margin_start(16)
        cell.set_margin_end(16)
        cell.append(label(value, "page-title", "num"))
        cell.append(label(caption, "fact-label", wrap=True))
        strip.append(cell)
    return strip


# --- notices, badges and the things a dialog still uses ----------------------


def notice(text: str, level: str = "quiet", action: tuple[str, str] | None = None) -> Gtk.Widget:
    """A standing fact reads quietly; only a real fault is allowed to shout.

    A notice about something a person can change carries the button that changes
    it, rather than naming a file and leaving them to find it.
    """
    bar = row(10)
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
        bar.append(button(text_label, "quiet", small=True, action=action_name))
    return bar


def heading(text: str) -> Gtk.Label:
    widget = label(text)
    widget.add_css_class("heading")
    widget.set_margin_top(6)
    return widget


def badge(text: str, kind: str) -> Gtk.Label:
    """Sentence case: a short word in capitals reads as a label, a phrase as shouting."""
    widget = label(text, "badge", kind)
    widget.set_valign(Gtk.Align.CENTER)
    return widget


def state_badge(state: str) -> Gtk.Label:
    """A run's outcome in the word a person would use for it."""
    kind, _ = STATE_BADGE.get(state, ("", "dialog-question-symbolic"))
    widget = badge(language.state_name(state), kind)
    widget.set_tooltip_text(language.state_meaning(state))
    return widget


def danger_chip(level: str) -> Gtk.Widget | None:
    """What this target does to the estate, in words, or nothing when it does none."""
    text = language.danger_badge(level)
    if not text:
        return None
    chip = label(text, "chip", level)
    chip.set_valign(Gtk.Align.CENTER)
    chip.set_ellipsize(3)
    chip.set_tooltip_text(language.danger_note(level))
    return chip


def dot(kind: str) -> Gtk.Widget:
    """A status dot, which is what a person scans a list of environments for."""
    marker = label("●", "status-dot", kind)
    marker.set_valign(Gtk.Align.CENTER)
    return marker


def slo_row(slo: Slo) -> Adw.ActionRow:
    """One objective inside a libadwaita list, for the dialogs that still use one."""
    line = Adw.ActionRow(title=slo.label, subtitle=f"{slo.target} over {slo.window}")
    if slo.has_data:
        bar = Gtk.ProgressBar(fraction=min((slo.attained or 0) / 100.0, 1.0))
        bar.add_css_class("slo-bar")
        bar.add_css_class("ok" if slo.status == "ok" else "breach")
        bar.set_valign(Gtk.Align.CENTER)
        bar.set_size_request(120, -1)
        line.add_suffix(bar)
        value = label(slo.value, "num")
        value.set_valign(Gtk.Align.CENTER)
        line.add_suffix(value)
    else:
        line.set_subtitle(f"{slo.target} over {slo.window} · {slo.blocked}")
        line.set_subtitle_lines(2)
        line.add_suffix(label(needs_of(slo), "tint-wait"))
    return line


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
    # row leaves it attached to a widget on its way out.
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
    """One recorded run inside a libadwaita list, for the places that still use one."""
    when = clock(run.started) if under_a_day else moment(run.started)
    subtitle = " · ".join(part for part in (run.environment, when) if part)
    headline = run.result.headline
    if headline:
        subtitle = f"{subtitle} · {headline}"
    elif run.exit_code not in (None, 0):
        subtitle = f"{subtitle} · exit {run.exit_code}"

    line = Adw.ActionRow(title=run.name, subtitle=subtitle, activatable=True)
    line.add_prefix(state_icon(run.state))
    if run.duration_s:
        line.add_suffix(label(took(run.duration_s), "tint-muted", "num", "mono"))
    line.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
    line.connect("activated", lambda *_: on_open(run.id))
    line.set_tooltip_text(f"{language.state_meaning(run.state)}\nStarted {run.started}")
    entries = [("Open this run", lambda: on_open(run.id))]
    if on_relaunch is not None and run.state != "running":
        entries.append(("Run it again", lambda: on_relaunch(run.id, False)))
    entries += [
        ("Copy the command", lambda: copy_to_clipboard(run.command)),
        ("Copy the run id", lambda: copy_to_clipboard(run.id)),
    ]
    attach_context_menu(line, entries)
    return line


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
        image.add_css_class("tint-ok")
    return image


def empty(
    title: str, description: str, icon: str = "dialog-information-symbolic"
) -> Adw.StatusPage:
    page = Adw.StatusPage(title=title, description=description, icon_name=icon)
    page.set_vexpand(True)
    return page


class Section(Gtk.Box):
    """A heading that folds away what is under it, and remembers that it was folded."""

    def __init__(self, title: str, *, folded: bool = False, on_fold=None, beside=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._on_fold = on_fold or (lambda _folded: None)

        line = row(8)
        self._chevron = Gtk.Image.new_from_icon_name(
            "pan-end-symbolic" if folded else "pan-down-symbolic"
        )
        line.append(self._chevron)
        line.append(label(title, "band"))

        self._toggle = Gtk.Button(child=line, has_frame=False)
        self._toggle.add_css_class("flat")
        self._toggle.set_hexpand(True)
        self._toggle.set_halign(Gtk.Align.START)
        # `fold(True)` folds. Revealed means not folded, so the state to ask
        # for is the current reveal.
        self._toggle.connect("clicked", lambda *_: self.fold(self._revealer.get_reveal_child()))

        head = row(10)
        head.append(self._toggle)
        if beside is not None:
            beside.set_valign(Gtk.Align.CENTER)
            head.append(beside)
        self.append(head)

        # No slide: a pane change is instant, and so is folding one open.
        self._revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.NONE, reveal_child=not folded
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
    top = row(12)
    heading_label = label(title, "page-title")
    heading_label.set_hexpand(True)
    top.append(heading_label)
    if control is not None:
        control.set_valign(Gtk.Align.CENTER)
        top.append(control)
    holder.append(top)
    if lede:
        holder.append(label(lede, "page-lede", wrap=True))
    return holder


def clamp(child: Gtk.Widget, maximum: int = CONTENT_WIDTH) -> Adw.Clamp:
    """The content well: no wider than a reader will follow the right-hand end of.

    It fills the stage and caps the content, rather than shrinking to whatever
    the content happens to want. Starting it at the left instead meant a page
    made of one card got the card's own width and nothing more, which is how
    the Actions list ended up half the room it had.
    """
    # The threshold is the maximum, so the well is the width it is given up to
    # 1080 and then stops. Below the two it grows sub-linearly, which reads as
    # a page that refuses to use the room it has.
    holder = Adw.Clamp(maximum_size=maximum, tightening_threshold=maximum, child=child)
    holder.set_margin_top(26)
    holder.set_margin_bottom(60)
    holder.set_margin_start(32)
    holder.set_margin_end(32)
    return holder


def scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    return Gtk.ScrolledWindow(child=child, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)


def sheet(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    """A dialog body that is as tall as its content and no taller."""
    return Gtk.ScrolledWindow(
        child=child,
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        propagate_natural_height=True,
        max_content_height=SHEET_MAX_HEIGHT,
    )


def clear(container: Gtk.Widget) -> None:
    """Empties a box, which every pane does before it draws itself again."""
    child = container.get_first_child()
    while child is not None:
        container.remove(child)
        child = container.get_first_child()
