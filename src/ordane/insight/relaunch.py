"""Running a recorded run again, and running it against only what failed.

Everything needed is already on disk: a run stores the argv it used, and the
parsed recap names every host with its failure counts. Nothing here asks the
repository anything: it re-reads what happened.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.command import Command
from ..presentation.language import MASK
from ..record.store import Run

# A run whose recorded command was masked cannot be replayed: what is stored is
# not what ran, and reconstructing it would mean guessing the secret.
MASKED = f"this run had a secret in it, so what was recorded is not what ran ({MASK})"


@dataclass(frozen=True)
class Replay:
    """A command to run again, or the reason there is not one."""

    command: Command | None = None
    limited_to: list[str] | None = None
    refusal: str = ""

    @property
    def possible(self) -> bool:
        return self.command is not None


def again(run: Run) -> Replay:
    """The same run, from the argv it recorded."""
    if not run.argv:
        return Replay(refusal="this run recorded no command")
    if any(MASK in part for part in run.argv):
        return Replay(refusal=MASKED)
    return Replay(command=Command.build(list(run.argv)))


def failed_hosts(run: Run) -> list[str]:
    """The hosts the recap said failed or could not be reached."""
    return [host.host for host in run.result.hosts if host.bad]


def against_failures(run: Run) -> Replay:
    """The same run, limited to the hosts that did not come back clean.

    Only for a run this console drove with `ansible-playbook`: a `make` wrapper
    may take no limit at all, and passing one it ignores would produce a run
    against everything wearing a label saying otherwise.
    """
    hosts = failed_hosts(run)
    if not hosts:
        return Replay(refusal="no host failed in this run")
    replay = again(run)
    if not replay.possible:
        return replay
    argv = list(replay.command.argv)
    if "ansible-playbook" not in argv[0] and not any("ansible-playbook" in a for a in argv[:2]):
        return Replay(
            refusal="this run went through `make`, which may take no host limit: "
            "run it again in full, or limit it in the control plane"
        )
    if "--limit" in argv:
        index = argv.index("--limit")
        argv[index + 1 : index + 2] = [",".join(hosts)]
    else:
        argv += ["--limit", ",".join(hosts)]
    return Replay(command=Command.build(argv), limited_to=hosts)
