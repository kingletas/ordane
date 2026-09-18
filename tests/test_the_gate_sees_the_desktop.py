"""The desktop half of the suite has to be able to fail where the gate runs.

Every GTK test opens with `pytest.importorskip("gi")`, which is right on a
machine with no desktop libraries and wrong on a runner. A skip nobody reads is
indistinguishable from a pass, and for as long as the bindings were missing in
CI the browser and the terminal carried the gate by themselves while the window,
the largest thing here, was checked by nothing.

`ORDANE_REQUIRE_GTK=1` is what the workflow sets. With it, absent bindings are a
failure. Without it, a machine with no desktop still runs everything else.
"""

from __future__ import annotations

import os

import pytest

INSISTED_ON = os.environ.get("ORDANE_REQUIRE_GTK") == "1"


@pytest.mark.skipif(not INSISTED_ON, reason="only where the gate insists on a desktop")
def test_the_bindings_every_other_desktop_test_skips_without():
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk

    Adw.init()
    assert Gtk.Label(label="drawn").get_text() == "drawn", "GTK is here and cannot build a label"
