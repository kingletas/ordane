"""One place to build a desktop page, so a test for one costs four lines.

Every GTK test used to repeat the same opening: import the bindings or skip,
name the versions, initialise libadwaita. Then each one built its own control
plane on disk and its own way of reading a widget tree back. That is why the
window, the largest part of this repository, had one page under test.

What a page needs is what the window hands it, so `a_scene` assembles the same
things `window.py` does and hands them over together.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ordane.core import catalog as catalog_module
from ordane.core import config as config_module
from ordane.insight import environments as env_module
from ordane.insight import health as health_module
from ordane.insight import metrics
from ordane.insight import setup as setup_module
from ordane.insight import verdict as verdict_module
from ordane.record.store import Run
from ordane.record.summary import HostResult, Summary

EXAMPLE_PLANE = Path(__file__).resolve().parents[1] / "examples" / "control-plane"

BARE_MAKEFILE = "help: ## Show this help\n\t@true\n"
BARE_CONFIG = "control_plane: bare/plane\nenvironments:\n  allow: [staging]\n"


@pytest.fixture(scope="session")
def adw():
    """libadwaita, initialised once, and a display or a reason there is not one."""
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk

    Adw.init()
    if Gdk.Display.get_default() is None:
        pytest.skip("GTK has no display. Run under `xvfb-run -a`, which is what CI does")
    return Adw


def page_text(widget) -> str:
    """Every label the page drew and every CSS class it used, as one string.

    Flat on purpose: most checks ask whether something reached the page at all.
    Where a value has to be tied to the row it belongs to, walk the tree in the
    test instead, the way the ledger parity check does for a grade.
    """
    from gi.repository import Gtk

    found: list[str] = []

    # A dialog keeps its content behind `get_child()` rather than in the child
    # list, so walking from the dialog itself finds nothing at all.
    child = getattr(widget, "get_child", None)
    if child is not None and widget.get_first_child() is None:
        inner = child()
        if inner is not None:
            widget = inner

    def walk(parent) -> None:
        child = parent.get_first_child()
        while child is not None:
            found.extend(child.get_css_classes())
            if isinstance(child, Gtk.Label):
                found.append(child.get_text())
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    return "\n".join(found)


def a_bare_plane(tmp_path: Path, name: str = "plane") -> Path:
    """A control plane with nothing in it, which is what a first launch looks at."""
    repo = tmp_path / name
    repo.mkdir(exist_ok=True)
    (repo / "Makefile").write_text(BARE_MAKEFILE, encoding="utf-8")
    (repo / ".ordane.yml").write_text(BARE_CONFIG, encoding="utf-8")
    return repo


def a_run(**kwargs) -> Run:
    """A run that succeeded five minutes ago, with whatever you change about it."""
    base = dict(
        id="r1",
        kind="target",
        name="deploy",
        environment="staging",
        params={},
        argv=["make", "deploy"],
        command="make deploy environment=staging",
        actor="ada",
        started=(datetime.now(UTC) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        state="succeeded",
        exit_code=0,
        # A run that ended carries both. Left unset, everything that draws or
        # measures a duration takes its "nothing to measure" branch, and four of
        # them are then never drawn in any page test.
        finished=(datetime.now(UTC) - timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        duration_s=112.0,
        summary=Summary(hosts=[HostResult(host="web-01", ok=3)], has_recap=True).as_record(),
    )
    base.update(kwargs)
    return Run(**base)


def a_failed_run(**kwargs) -> Run:
    """The other direction, which is the one a page is most likely to get wrong."""
    base = dict(
        id="r2",
        name="deploy",
        state="failed",
        exit_code=2,
        summary=Summary(
            hosts=[HostResult(host="web-01", ok=1, failed=1, unreachable=1)], has_recap=True
        ).as_record(),
    )
    base.update(kwargs)
    return a_run(**base)


@dataclass(frozen=True)
class Scene:
    """What the window works out before it hands a page anything."""

    repo: Path
    state_dir: Path
    config: object
    catalog: object
    runs: list
    snapshot: object
    verdict: object
    setup: object
    standings: list


def _history_relative_to_the_repo() -> str:
    """Where the window looks for the release history, asked of the window's own default.

    Imported here rather than at the top: this file is collected by the probe
    that runs the suite with no toolkit installed, and the desktop package needs
    GTK to import at all.
    """
    from ordane.desktop import app as app_module

    return app_module.Settings.history


def a_scene(repo: Path, tmp_path: Path, *, runs=()) -> Scene:
    """Everything a page is given, assembled the way `window.py` assembles it."""
    runs = list(runs)
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    # The same file the window reads. Pointed anywhere else, every scene is a
    # control plane that has never released, and the pages that draw a measured
    # figure are only ever asked to draw the dormant one.
    history_path = repo / _history_relative_to_the_repo()
    events_path = state_dir / "deployments.jsonl"

    config = config_module.load(repo)
    catalog = catalog_module.build(repo, config)
    snapshot = metrics.snapshot(
        history_path=history_path,
        events_path=events_path,
        runs=runs,
        slo_specs=config.slos,
        scope=config.metric_environments,
    )
    health = health_module.assess(catalog=catalog, config=config, snapshot=snapshot, runs=runs)
    setup = setup_module.assess(
        catalog=catalog,
        config=config,
        snapshot=snapshot,
        runs=runs,
        repo=repo,
        history_path=history_path,
    )
    return Scene(
        repo=repo,
        state_dir=state_dir,
        config=config,
        catalog=catalog,
        runs=runs,
        snapshot=snapshot,
        verdict=verdict_module.decide(catalog=catalog, health=health, setup=setup, runs=runs),
        setup=setup,
        standings=env_module.standings(
            environments=catalog.environments,
            runs=runs,
            # Keyed by name, as the window keys it from the inventories it read.
            # Keyed by the environment object instead, every lookup misses and
            # the standings silently take their unknown-host branch.
            hosts={e.name: 2 for e in catalog.environments},
        ),
    )
