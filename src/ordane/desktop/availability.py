"""Whether this machine can run the desktop console at all.

The doctor cannot ask this itself: it lives in a layer that knows no front end,
and importing GTK to find out would put the toolkit inside the engine.
"""

from __future__ import annotations

from ..core.doctor import OK, WARN, Finding


def finding() -> Finding:
    """One finding, and it never raises: a missing toolkit is a report."""
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
    except (ImportError, ValueError) as exc:
        return Finding(
            WARN,
            "The desktop console cannot start here",
            str(exc),
            "sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1: "
            "every view is also available in this terminal.",
        )
    return Finding(OK, "GTK 4 and libadwaita are available", "the desktop console will start")
