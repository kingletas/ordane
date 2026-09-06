"""Every keyboard shortcut, once, as data.

The window registers them from this table, the menu draws its accelerators from
it and the shortcuts window is generated from it, so the three cannot disagree.
A test reads the user guide against it, because a documented key that does
something else is the kind of error nothing else catches.
"""

from __future__ import annotations

from dataclasses import dataclass

# GTK spells these out; a keyboard has them printed on it.
SYMBOLS = {"comma": ",", "period": ".", "question": "?", "slash": "/", "space": "Space"}


@dataclass(frozen=True)
class Key:
    """One shortcut: the accelerator, what it does, and where it is listed."""

    accelerator: str
    action: str
    label: str
    group: str

    @property
    def pretty(self) -> str:
        """`<Control>r` as a person writes it: Ctrl+R."""
        text = self.accelerator.replace("<Control>", "Ctrl+").replace("<Shift>", "Shift+")
        text = text.replace("<Alt>", "Alt+")
        head, _, tail = text.rpartition("+")
        tail = SYMBOLS.get(tail, tail.upper() if len(tail) == 1 else tail)
        return f"{head}+{tail}" if head else tail


KEYS = (
    Key("<Control>1", "win.page::dashboard", "Go to Health", "Move around"),
    Key("<Control>2", "win.page::actions", "Go to Actions", "Move around"),
    Key("<Control>3", "win.page::runs", "Go to Runs", "Move around"),
    Key("<Control>4", "win.page::estate", "Go to the Estate", "Move around"),
    Key("Escape", "win.back", "Leave the run you are watching", "Move around"),
    Key("<Alt>Left", "win.go-back", "Back to the page before this one", "Move around"),
    Key("<Alt>Right", "win.go-forward", "Forward again", "Move around"),
    Key("<Control>f", "win.find", "Find a target", "Do something"),
    Key("<Control>o", "win.open", "Open another control plane", "Do something"),
    Key("<Control>b", "win.rail", "Show or hide the rail", "This window"),
    Key("<Control>r", "win.refresh", "Re-read the repository", "Do something"),
    Key("<Control>comma", "win.configure", "Open the configuration file", "Do something"),
    Key("<Control>question", "win.shortcuts", "Show these shortcuts", "This window"),
    Key("F1", "win.guide", "Open the user guide", "This window"),
    Key("<Control>w", "win.close", "Close the window", "This window"),
)

GROUPS = ("Move around", "Do something", "This window")


def by_group() -> list[tuple[str, list[Key]]]:
    """The table split for display, in the order the groups are declared."""
    return [(name, [k for k in KEYS if k.group == name]) for name in GROUPS]


def for_action(action: str) -> Key | None:
    return next((k for k in KEYS if k.action == action), None)
