"""The two faces the interface is set in, and how GTK is made to find them.

Manrope carries every word; IBM Plex Mono carries anything a person could paste
into a terminal. Neither ships with a Linux desktop, so both are bundled: a
window that falls back to whatever is installed is a different design.

GTK resolves a family name through fontconfig, and fontconfig cannot see
package data. `teach_fontconfig` points it at the bundled directory, and it has
to run before the first GTK import.

Usage:
  from .fonts import teach_fontconfig
  teach_fontconfig()          # before `gi.repository` is touched
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

PACKAGE = "ordane.desktop.assets"

SANS = "Manrope"
MONO = "IBM Plex Mono"

# Family, file. One format rather than two: fontconfig cannot read WOFF2.
FACES = (
    (SANS, "Manrope-Variable.ttf"),
    (MONO, "IBMPlexMono-Regular.ttf"),
    (MONO, "IBMPlexMono-Medium.ttf"),
    (MONO, "IBMPlexMono-SemiBold.ttf"),
)

# What is written when a bundled face cannot be reached, so the fallback is a
# decision rather than whatever the desktop happens to have first.
SANS_STACK = f"{SANS}, Cantarell, 'Segoe UI', sans-serif"
MONO_STACK = f"'{MONO}', 'Cascadia Mono', 'DejaVu Sans Mono', monospace"


def directory() -> Path | None:
    """Where the bundled files are, or nothing when they were not packaged."""
    found = resources.files(PACKAGE).joinpath("fonts")
    return Path(str(found)) if found.is_dir() else None


def fontconfig_fragment(where: str) -> str:
    """A fontconfig file naming the bundled directory, for a run from a checkout."""
    return (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n'
        "<fontconfig>\n"
        '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
        f"  <dir>{where}</dir>\n"
        "</fontconfig>\n"
    )


def teach_fontconfig(cache_home: Path | None = None) -> bool:
    """Points fontconfig at the bundled faces. Says whether it managed to.

    Stands aside for a FONTCONFIG_FILE somebody set on purpose, and never
    raises: a read-only cache costs the design its two faces, not its start.
    """
    if os.environ.get("FONTCONFIG_FILE"):
        return False
    where = directory()
    if where is None:
        return False
    root = cache_home or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    fragment = root / "ordane" / "fonts.conf"
    try:
        fragment.parent.mkdir(parents=True, exist_ok=True)
        fragment.write_text(fontconfig_fragment(str(where)), encoding="utf-8")
    except OSError:
        return False
    os.environ["FONTCONFIG_FILE"] = str(fragment)
    return True
