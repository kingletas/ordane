"""The same console, printed. Every view here reads exactly what the web pages read.

The web app and this share their catalogue, config, metrics, runner and store,
so neither can drift from the other and the browser is optional.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from ..core.catalog import Catalog
from ..core.config import CONFIG_NAME, Config
from ..insight.metrics import Snapshot
from ..presentation import language
from ..presentation.text import moment, took
from ..record.store import Run

_TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

DIM = "\033[2m" if _TTY else ""
BOLD = "\033[1m" if _TTY else ""
RED = "\033[31m" if _TTY else ""
GREEN = "\033[32m" if _TTY else ""
YELLOW = "\033[33m" if _TTY else ""
BLUE = "\033[34m" if _TTY else ""
OFF = "\033[0m" if _TTY else ""

STATE_COLOUR = {
    "succeeded": GREEN,
    "failed": RED,
    "error": RED,
    "cancelled": YELLOW,
    "running": BLUE,
}


def heading(text: str) -> None:
    print(f"\n{BOLD}{text}{OFF}")
    print(f"{DIM}{'─' * len(text)}{OFF}")


def state(run: Run) -> str:
    """The same word the desktop and the browser use for this outcome."""
    return f"{STATE_COLOUR.get(run.state, '')}{language.state_name(run.state).lower()}{OFF}"


def dashboard(catalog: Catalog, snapshot: Snapshot, runs: list[Run], repo: Path) -> None:
    """Everything the dashboard page shows, in a terminal."""
    print(f"\n{BOLD}Ordane{OFF} {DIM}— {repo}{OFF}")

    heading("Delivery performance")
    for measure in snapshot.measures:
        name = language.measure_name(measure.key, measure.label)
        if not measure.has_data:
            needs = language.measure_needs(measure.key) or measure.blocked
            print(f"  {name:<26} {YELLOW}setup needed{OFF}  {DIM}{needs}{OFF}")
            continue
        print(f"  {name:<26} {BOLD}{measure.value:<14}{OFF}{DIM}{measure.detail}{OFF}")
        if measure.trend is not None:
            print(f"  {'':<26} {DIM}{measure.trend.text}{OFF}")

    if snapshot.slos:
        heading("Service objectives")
        for slo in snapshot.slos:
            target = f"{slo.target} / {slo.window}"
            if slo.has_data:
                mark = f"{GREEN}✓{OFF}" if slo.status == "ok" else f"{RED}✗{OFF}"
                print(f"  {mark} {slo.label:<42} {target:<14} {BOLD}{slo.value}{OFF}")
            else:
                print(
                    f"  {DIM}·{OFF} {slo.label:<42} {target:<14} "
                    f"{YELLOW}setup needed{OFF} {DIM}— {slo.blocked}{OFF}"
                )

    if snapshot.notes:
        heading("Why measures are missing")
        for note in snapshot.notes:
            print(f"  {DIM}• {note}{OFF}")

    heading("Environments")
    for environment in catalog.environments:
        blocked = environment.blocked_reason
        mark = f"{DIM}·{OFF}" if blocked else f"{GREEN}✓{OFF}"
        note = f"{DIM}{blocked}{OFF}" if blocked else "launchable"
        print(f"  {mark} {environment.name:<18} {note}")

    launchable = catalog.launchable_environments
    if not launchable:
        print(
            f"\n  {YELLOW}Read-only.{OFF} No environment has been chosen, so nothing can be "
            f"launched.\n  {DIM}Add one under environments.allow in {repo}/{CONFIG_NAME}, "
            f"or open the desktop console and use Manage environments.{OFF}"
        )

    heading("Recent runs")
    if not runs:
        print(f"  {DIM}nothing has run through this console yet{OFF}")
        return
    for run in runs[:10]:
        when = moment(run.started)
        print(f"  {when:<20} {run.name:<22} {run.environment:<12} {state(run)}")


MARK = {"ok": f"{GREEN}✓{OFF}", "warn": f"{YELLOW}!{OFF}", "fail": f"{RED}✗{OFF}"}


def checkup(report, repo: Path) -> None:
    """The doctor's findings, each with what to do about it."""
    print(f"\n{BOLD}{report.headline}{OFF} {DIM}— {repo}{OFF}\n")
    for finding in report.findings:
        print(f"  {MARK.get(finding.level, ' ')} {BOLD}{finding.title}{OFF}")
        if finding.detail:
            print(f"      {DIM}{finding.detail}{OFF}")
        if finding.fix:
            print(f"      {finding.fix}")
    print()


def actions(catalog: Catalog, config: Config) -> None:
    """The action list, grouped exactly as the other two front ends group it.

    In the order the config declared, which is a decision about how the work is
    done: sorting the groups alphabetically here would throw it away.
    """
    groups: dict[str, list] = {}
    for target in catalog.targets:
        groups.setdefault(target.group, []).append(target)

    for group in config.sort_groups(groups):
        heading(group)
        for target in groups[group]:
            danger = ""
            note = language.danger_badge(target.danger)
            if note:
                colour = RED if target.danger == "high" else YELLOW
                danger = f" {colour}[{note.lower()}]{OFF}"
            print(f"  {target.name:<24}{danger} {DIM}{target.description}{OFF}")
            for name, param in target.params.items():
                need = "required" if param.required else "optional"
                help_text = f": {param.help}" if param.help else ""
                print(f"      {DIM}{name} ({need}){help_text}{OFF}")


def history(runs: list[Run], limit: int) -> None:
    if not runs:
        print(f"{DIM}no runs recorded{OFF}")
        return
    for run in runs[:limit]:
        summary = run.result.headline
        tail = f"  {DIM}{summary}{OFF}" if summary else ""
        print(
            f"{moment(run.started):<20} {run.id}  {run.name:<22} {run.environment:<12} "
            f"{state(run):<20} {took(run.duration_s):>13}{tail}"
        )


def run_detail(run: Run, output: str, tail: int) -> None:
    """One run: what it was, what Ansible reported, and the end of its output."""
    print(f"\n{BOLD}{run.name}{OFF}  {state(run)}")
    print(f"  {DIM}command    {OFF}{run.command}")
    if run.environment:
        # A run of the control plane's own checks reaches none, and a label with
        # nothing after it reads as a missing value rather than an absent one.
        print(f"  {DIM}environment{OFF} {run.environment}")
    print(f"  {DIM}started    {OFF}{moment(run.started)}   {DIM}by{OFF} {run.actor}")
    if run.finished:
        print(
            f"  {DIM}finished   {OFF}{moment(run.finished)}   {took(run.duration_s)}   "
            f"exit {run.exit_code}"
        )

    result = run.result
    if result.has_recap:
        heading("Result")
        for host in result.hosts:
            colour = RED if host.bad else (YELLOW if host.changed else GREEN)
            print(
                f"  {colour}{host.host:<24}{OFF} ok={host.ok:<5} changed={host.changed:<5} "
                f"failed={host.failed:<3} unreachable={host.unreachable:<3} "
                f"skipped={host.skipped}"
            )
    if result.failures:
        heading("Failures")
        for failure in result.failures:
            print(f"  {RED}{failure.kind}{OFF} on {BOLD}{failure.host}{OFF} in {failure.task}")
            if failure.message:
                print(f"      {DIM}{failure.message}{OFF}")
        if result.truncated_failures:
            print(f"  {DIM}… and {result.truncated_failures} more{OFF}")

    if output and tail:
        heading(f"Output (last {tail} lines)")
        for line in output.splitlines()[-tail:]:
            print(f"  {line}")


def follow(active, poll: float = 0.2) -> int:
    """Prints a live run's output as it arrives, then its result."""
    for chunk in active.stream():
        if chunk:
            sys.stdout.write(chunk)
            sys.stdout.flush()
        else:
            time.sleep(poll)
    run = active.run
    print(f"\n{state(run)} in {took(run.duration_s) or 'no time at all'} (exit {run.exit_code})")
    headline = run.result.headline
    if headline:
        print(f"{DIM}{headline}{OFF}")
    return 0 if run.exit_code == 0 else 1
