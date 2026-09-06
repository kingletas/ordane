"""Which sections this person keeps folded away, remembered between sessions.

A page opens the way it was left. Nothing here belongs in the control plane's
configuration: it is about this window, not the estate.
"""

from __future__ import annotations

from pathlib import Path

from . import geometry


class Folding:
    """Reads once and writes through, so a fold survives a restart."""

    def __init__(self, state_dir: Path | None = None) -> None:
        self._state_dir = state_dir
        self._folded = geometry.folded(state_dir) if state_dir is not None else set()

    def is_folded(self, key: str) -> bool:
        return key in self._folded

    def remember(self, key: str, folded: bool) -> None:
        self._folded.add(key) if folded else self._folded.discard(key)
        if self._state_dir is not None:
            geometry.save_folded(self._state_dir, key, folded)
