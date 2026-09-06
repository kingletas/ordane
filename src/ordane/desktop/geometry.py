"""What this person's window looks like, remembered between sessions.

A console reopened at the same size every time is one somebody resizes every
time, and a rail somebody has turned off should stay off. None of this belongs
in the control plane's configuration: it is about the window, not the estate.
"""

from __future__ import annotations

import json
from pathlib import Path

FILE_NAME = "window.json"

# What it opens at the first time, before there is anything to remember.
DEFAULT = (1180, 820)

# Below this a saved size is a mistake rather than a preference: a window
# restored to nothing looks exactly like one that failed to start.
MINIMUM = (640, 480)

# Where the things this console does live: the rail, the menu button, or both.
# Neither is wrong: the rail is faster to read and the menu is out of the way —
# so it is a choice rather than a default somebody has to work around.
RAIL = "rail"
MENU = "menu"
BOTH = "both"
NAVIGATION = (
    (MENU, "Menu only", "The header carries the views, the search and which control plane."),
    (BOTH, "Rail and menu", "The rail is open and the menu button stays in the header."),
    (RAIL, "Rail only", "The header keeps only the views."),
)
# The rail is a list of things done once a session, and it was permanently in
# front of the content it describes. It is a choice now rather than the default.
DEFAULT_NAVIGATION = MENU


def restore(state_dir: Path) -> tuple[int, int, bool]:
    """The remembered size and whether it was maximised, or the defaults."""
    saved = _read(state_dir)
    try:
        width = int(saved["width"])
        height = int(saved["height"])
        maximised = bool(saved.get("maximised", False))
    except (ValueError, KeyError, TypeError):
        return (*DEFAULT, False)
    if width < MINIMUM[0] or height < MINIMUM[1]:
        return (*DEFAULT, maximised)
    return width, height, maximised


def navigation(state_dir: Path) -> str:
    """Which of the rail and the menu this person keeps."""
    chosen = str(_read(state_dir).get("navigation", "") or "")
    return chosen if chosen in {key for key, _, _ in NAVIGATION} else DEFAULT_NAVIGATION


def folded(state_dir: Path) -> set[str]:
    """The sections this person has folded away, so they stay folded."""
    saved = _read(state_dir).get("folded", [])
    return {str(one) for one in saved} if isinstance(saved, list) else set()


def save_folded(state_dir: Path, key: str, is_folded: bool) -> None:
    keys = folded(state_dir)
    keys.add(key) if is_folded else keys.discard(key)
    _write(state_dir, {"folded": sorted(keys)})


def save(state_dir: Path, width: int, height: int, maximised: bool) -> None:
    """Records the size. Never raises: this is a convenience, not a promise."""
    _write(state_dir, {"width": width, "height": height, "maximised": maximised})


def save_navigation(state_dir: Path, chosen: str) -> None:
    _write(state_dir, {"navigation": chosen})


def _read(state_dir: Path) -> dict:
    try:
        saved = json.loads((state_dir / FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _write(state_dir: Path, values: dict) -> None:
    """Merges into what is there: two settings, written at different moments."""
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / FILE_NAME).write_text(
            json.dumps({**_read(state_dir), **values}), encoding="utf-8"
        )
    except OSError:
        return
