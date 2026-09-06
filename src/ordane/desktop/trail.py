"""Where this window has been, so a back button has somewhere to go.

A mouse has two buttons on its side and every other application on this desktop
uses them to step back and forward. This is the list they step through.
"""

from __future__ import annotations

# Long enough to walk back through an afternoon, short enough to stay a list.
DEPTH = 40


class Trail:
    """The pages visited, and where in them this window currently is."""

    def __init__(self) -> None:
        self._pages: list[str] = []
        self._at = -1

    @property
    def pages(self) -> list[str]:
        return list(self._pages)

    def visit(self, page: str) -> None:
        """Records a page. Anything ahead of here is dropped, as in a browser."""
        if not page or (self._at >= 0 and self._pages[self._at] == page):
            return
        del self._pages[self._at + 1 :]
        self._pages.append(page)
        if len(self._pages) > DEPTH:
            del self._pages[0]
        self._at = len(self._pages) - 1

    @property
    def can_go_back(self) -> bool:
        return self._at > 0

    @property
    def can_go_forward(self) -> bool:
        return -1 < self._at < len(self._pages) - 1

    def back(self) -> str | None:
        if not self.can_go_back:
            return None
        self._at -= 1
        return self._pages[self._at]

    def forward(self) -> str | None:
        if not self.can_go_forward:
            return None
        self._at += 1
        return self._pages[self._at]
