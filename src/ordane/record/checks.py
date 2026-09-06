"""A run of a control plane's own checks, recorded like anything else that ran.

**A suite that passed before a deploy is evidence, and evidence that is not
written down is a claim.** The checks were shown and forgotten: the window drew
their result and the history held nothing, so *the checks passed before this
went out* was true and unprovable an hour later.

It is a `Run` like any other, under its own kind and carrying no labels, so it
sits in the history beside the deploy it gated and can never be counted as one.
"""

from __future__ import annotations

from pathlib import Path

from ..core import identity
from .store import Run, RunStore, new_id, now
from .summary import Failure, Summary

# The kind a suite is recorded under. Not `target`: nothing here ran a
# playbook, and nothing here reached a host.
CHECKS = "checks"

NAME = "checks"


def record(
    store: RunStore,
    report,
    *,
    suite,
    plane: str,
    repo: Path,
    environment: str = "",
    started: str = "",
    sequence: str = "",
) -> Run:
    """Writes the suite's outcome and its output. Returns the run it wrote."""
    actor = identity.who()
    seconds = round(sum(one.seconds for one in report.results), 2)
    run = Run(
        id=new_id(),
        kind=CHECKS,
        name=NAME,
        environment=environment,
        params={},
        argv=["ordane", "checks"],
        command=f"ordane checks  ·  {suite.image}",
        actor=actor.name,
        started=started or now(),
        repo=str(repo),
        plane=plane,
        host=actor.host,
        installation=identity.installation(store.root),
        state="succeeded" if report.ok else "failed",
        finished=now(),
        duration_s=seconds,
        exit_code=0 if report.ok else 1,
        # No labels, ever: a suite that counted as a deploy would move a
        # delivery measure without anything having been deployed.
        labels={},
        sequence=sequence,
        summary=_as_summary(report).as_record(),
    )
    store.prepare()
    try:
        store.output_path(run.id).write_text(transcript(report, suite), encoding="utf-8")
    except OSError:
        # The record is worth more than the transcript, and a full disk must
        # not lose both.
        pass
    store.append(run)
    return run


def transcript(report, suite) -> str:
    """What a person opening this run needs to read, summary first."""
    lines = [f"{report.summary}  ·  {suite.image}", ""]
    for result in report.results:
        lines.append(f"--- {result.state.upper()}  {result.check.name}")
        lines.append(f"    {result.check.display}")
        if result.output:
            lines.append("")
            lines.append(result.output)
        lines.append("")
    if report.error:
        lines.append(report.error)
    return "\n".join(lines).strip() + "\n"


def _as_summary(report) -> Summary:
    """Each failing check as a failure, so the run view lists them by name.

    `has_recap` stays false: there is no `PLAY RECAP` here because no play ran,
    and pretending otherwise would put host counts on a thing with no hosts.
    """
    return Summary(
        failures=[
            Failure(
                host=one.check.name,
                task=one.check.display,
                kind="failed",
                message=_last_line(one.output),
            )
            for one in report.failed
        ]
    )


def _last_line(text: str) -> str:
    kept = [line for line in (text or "").splitlines() if line.strip()]
    return kept[-1][:300] if kept else ""
