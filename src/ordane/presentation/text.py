"""Small language helpers, so the interface reads like English rather than a log."""

from __future__ import annotations

from datetime import UTC, datetime

IRREGULAR = {
    "is": "are",
    "was": "were",
    "has": "have",
    "this": "these",
    "it": "they",
}


def plural(count: int, singular: str, plural_form: str = "") -> str:
    """`1 environment`, `3 environments`: never `1 environment(s)`."""
    word = singular if count == 1 else (plural_form or _plural_of(singular))
    return f"{count} {word}"


def _plural_of(word: str) -> str:
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if word.endswith("y") and not word.endswith(("ay", "ey", "iy", "oy", "uy")):
        return word[:-1] + "ies"
    return word + "s"


def verb(count: int, singular: str) -> str:
    """Agrees a verb with a count: `1 run has`, `2 runs have`."""
    return singular if count == 1 else IRREGULAR.get(singular, singular)


def sentence(items: list[str]) -> str:
    """`a`, `a and b`, `a, b and c`."""
    items = [i for i in items if i]
    if len(items) <= 1:
        return items[0] if items else ""
    return f"{', '.join(items[:-1])} and {items[-1]}"


def elide(text: str, limit: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def moment(stamp: str, now: datetime | None = None) -> str:
    """`today at 13:27` rather than `2026-09-05T13:27:01Z`.

    The exact stamp is kept for a tooltip; what a person reads is where the run
    sits relative to the day they are having.
    """
    when = _parse(stamp)
    if when is None:
        return stamp
    when = when.astimezone()
    today = (now or datetime.now(UTC)).astimezone().date()
    days = (today - when.date()).days
    clock = when.strftime("%H:%M")
    if days == 0:
        return f"today at {clock}"
    if days == 1:
        return f"yesterday at {clock}"
    if 0 < days < 7:
        return f"{when.strftime('%A')} at {clock}"
    return f"{when.day} {when.strftime('%b')} at {clock}"


def day(stamp: str, now: datetime | None = None) -> str:
    """`Today`, `Yesterday`, `Friday`, `3 September`: a heading over a day's runs."""
    when = _parse(stamp)
    if when is None:
        return "Undated"
    when = when.astimezone()
    today = (now or datetime.now(UTC)).astimezone().date()
    days = (today - when.date()).days
    if days == 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if 0 < days < 7:
        return when.strftime("%A")
    if when.year == today.year:
        return f"{when.day} {when.strftime('%B')}"
    return f"{when.day} {when.strftime('%B %Y')}"


def clock(stamp: str) -> str:
    """`13:27`, for a row that already sits under the day it happened on."""
    when = _parse(stamp)
    return when.astimezone().strftime("%H:%M") if when else stamp


def took(seconds: float | None) -> str:
    """`under a second`, `12s`, `3m 20s`, `1h 04m`: never `0.0s`."""
    if not seconds:
        return ""
    if seconds < 1:
        return "under a second"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60):02d}s"
    return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60):02d}m"


def since(stamp: str, now: datetime | None = None) -> float | None:
    """Seconds elapsed since a stamp, or None when it cannot be read."""
    when = _parse(stamp)
    if when is None:
        return None
    return max(0.0, ((now or datetime.now(UTC)) - when).total_seconds())


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def ago(seconds: float, verb: str = "read") -> str:
    """`read just now`, `asked 3 minutes ago`, so a figure is never taken as live."""
    if seconds < 45:
        return f"{verb} just now"
    if seconds < 3600:
        return f"{verb} {plural(int(seconds // 60), 'minute')} ago"
    return f"{verb} {plural(int(seconds // 3600), 'hour')} ago"
