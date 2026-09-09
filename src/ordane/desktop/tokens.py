"""The Bridge palette and type scale, as data.

One source for both the stylesheet and the things cairo paints. The stylesheet
reads them as `@define-color`; a chart reads them as strings. Two hand-kept
copies of a colour is how a bar ends up a different green from the pill beside
it.

The base is Stone, hardened: warm neutral greys and a deep pine, with the rail
darkened into an instrument body. Cards are lighter than the canvas and never
white — this is equipment, not paper.

Four status states and no more. `waiting` is blue on purpose: configuration
that has not been finished is not a fault, and spending amber on it leaves
nothing to escalate to when something actually breaks.
"""

from __future__ import annotations

LIGHT = "light"
DARK = "dark"

# The rail is the same instrument body in both schemes: it is the one surface
# that does not belong to the desk it sits on.
RAIL = {
    "rail": "#171C1B",
    "rail-raised": "#1F2523",
    "rail-edge": "#0F1312",
    "rail-line": "#252C2A",
    "rail-fg": "#AEB6B3",
    "rail-fg-strong": "#F2F4F3",
    # Lifted off the prototype's #6E7976, which reads at 3.8:1 on the rail.
    "rail-muted": "#828D8A",
    "rail-accent": "#7FBBA3",
    "rail-hover": "#232A28",
    "rail-active": "#2B3532",
    "rail-card": "#1E2523",
    "rail-card-line": "#2B3331",
    "rail-card-hover": "#232B29",
    "rail-chip": "#2A3230",
    "rail-chip-fg": "#9FB0AA",
    "rail-chip-clean": "#8CC0A9",
    "rail-key": "#262E2C",
    "rail-key-line": "#333C39",
    "rail-key-fg": "#A9B3B0",
    "rail-card-edge": "#374039",
    "rail-name": "#EAEEEC",
}

# A run's output reads as a terminal in both schemes, for the same reason.
LOG = {
    "log-bg": "#1B211F",
    "log-fg": "#C6CFCB",
    # Lifted off the prototype's #66736E, which reads at 3.3:1 on the log.
    "log-time": "#7C8B85",
    "log-ok": "#8CC0A9",
    "log-warn": "#D3AC63",
}

SCHEMES = {
    LIGHT: {
        "canvas": "#E7E6E1",
        "canvas-sunken": "#DEDCD5",
        "canvas-hover": "#D8D6CE",
        "card": "#F7F6F2",
        "card-head": "#F1F0EB",
        "card-hover": "#FBFAF7",
        "card-inset": "#EDECE7",
        "card-inset-line": "#CFCDC5",
        "ink": "#1B1F1E",
        "ink-2": "#4A524F",
        # The prototype's #7C837F reads at 3.1:1 on the canvas. Same hue, four
        # steps darker, so unit labels and axis text clear the body-text floor.
        "ink-3": "#626865",
        "line": "#D5D3CC",
        "line-soft": "#E2E0D9",
        "ready": "#1F5E4A",
        "ready-bg": "#E4EDE8",
        "ready-line": "#C9DCD2",
        "waiting": "#3C5A78",
        "waiting-bg": "#E4EAF0",
        "waiting-line": "#CFD9E3",
        # #95681A reads at 3.9:1 on the canvas and 4.1:1 on its own tint.
        "degraded": "#875E18",
        "degraded-bg": "#F2E9D6",
        "failed": "#9E382A",
        "failed-bg": "#F3E1DD",
        "cell-empty": "#E4E2DA",
        "cell-hatch": "#D8D6CE",
        "cell-ok": "#BFD6CB",
        "tick-idle": "#CFD8D3",
        "track": "#E4E2DA",
        "seg-track": "#E7E5DE",
        # What a filled button's own text is. White on light pine is 2.2:1, so
        # in the dark scheme the fill keeps its colour and the text goes dark.
        "on-ready": "#FFFFFF",
        "on-waiting": "#FFFFFF",
        "on-failed": "#FFFFFF",
        "on-rail-active": "#FFFFFF",
    },
    DARK: {
        "canvas": "#101413",
        "canvas-sunken": "#161B1A",
        "canvas-hover": "#1D2422",
        "card": "#1B2120",
        "card-head": "#212827",
        "card-hover": "#232A29",
        "card-inset": "#161B1A",
        "card-inset-line": "#333B39",
        "ink": "#EAEEEC",
        "ink-2": "#A9B3AF",
        "ink-3": "#8A938F",
        "line": "#2C3432",
        "line-soft": "#262E2C",
        "ready": "#74BC9C",
        "ready-bg": "#172C25",
        "ready-line": "#2A463C",
        "waiting": "#8CB0D2",
        "waiting-bg": "#17232E",
        "waiting-line": "#2A3B4A",
        "degraded": "#D5A54A",
        "degraded-bg": "#2C2413",
        "failed": "#E38A7B",
        "failed-bg": "#2F1B17",
        "cell-empty": "#252D2B",
        "cell-hatch": "#313A38",
        "cell-ok": "#33564A",
        "tick-idle": "#3A4442",
        "track": "#252D2B",
        "seg-track": "#232B29",
        "on-ready": "#0E1614",
        "on-waiting": "#0C1218",
        "on-failed": "#1B0E0B",
        "on-rail-active": "#F4F7F6",
    },
}

# What a status word is called, and which pair of colours says it.
READY = "ready"
WAITING = "waiting"
DEGRADED = "degraded"
FAILED = "failed"
STATES = (READY, WAITING, DEGRADED, FAILED)


def palette(scheme: str) -> dict[str, str]:
    """Every colour name the stylesheet can ask for, in one scheme."""
    return {**RAIL, **LOG, **SCHEMES.get(scheme, SCHEMES[LIGHT])}


def colour(name: str, scheme: str = LIGHT) -> str:
    return palette(scheme)[name]


def definitions(scheme: str) -> str:
    """The `@define-color` block the stylesheet is prepended with."""
    return "\n".join(f"@define-color {name} {value};" for name, value in palette(scheme).items())
