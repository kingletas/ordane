"""Who is running this, and on what: read from the process, not from the environment.

`$USER` is a string anybody can set, and under `sudo` it commonly still says
who you were before. A run recorded against the wrong person is worse than one
recorded against nobody, so this asks the operating system instead.
"""

from __future__ import annotations

import os
import pwd
import socket
from dataclasses import dataclass

ROOT_UID = 0

# One random id per installation, written once. A run id is a timestamp and a
# little randomness, which is unique on one machine and not across several —
# (installation, id) is the pair that is.
INSTALLATION_FILE = "installation-id"


@dataclass(frozen=True)
class Actor:
    """The account a run actually runs as, and the machine it runs on."""

    user: str
    uid: int
    host: str
    # Who invoked `sudo`, where that is how this became root. Evidence about
    # the escalation, not a second identity.
    escalated_from: str = ""

    @property
    def is_root(self) -> bool:
        return self.uid == ROOT_UID

    @property
    def name(self) -> str:
        """`ada@thinkpad`, which is what a shared history has to say."""
        return f"{self.user}@{self.host}" if self.host else self.user

    @property
    def summary(self) -> str:
        """`ada@box`, or `root@box, via sudo from ada`."""
        parts = [self.name]
        if self.is_root and self.user != "root":
            parts.append("uid 0")
        if self.escalated_from:
            parts.append(f"via sudo from {self.escalated_from}")
        return ", ".join(parts)


def who() -> Actor:
    """The effective user, which is the one whose permissions a run will have."""
    uid = os.geteuid()
    try:
        user = pwd.getpwuid(uid).pw_name
    except KeyError:
        user = str(uid)
    return Actor(
        user=user,
        uid=uid,
        host=_host(),
        escalated_from=os.environ.get("SUDO_USER", "") if uid == ROOT_UID else "",
    )


def installation(state_dir) -> str:
    """This installation's id, generated on first use and never changed.

    Never raises: a state directory that cannot be written gives an empty id,
    which is exactly as unique as not having one and does not stop a run.
    """
    import secrets
    from pathlib import Path

    path = Path(state_dir) / INSTALLATION_FILE
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    minted = secrets.token_hex(4)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(minted + "\n", encoding="utf-8")
    except OSError:
        return ""
    return minted


def _host() -> str:
    try:
        return socket.gethostname().split(".")[0]
    except OSError:
        return ""


# What a console running as root is: not refused, and not quiet either. Nothing
# here needs those permissions, and a run recorded as root is a run nobody can
# be held to.
ROOT_WARNING = (
    "Running as root. Every playbook this launches gets root on this machine, "
    "the run history is written as root, and the file it writes may stop being "
    "readable by your own account. Ansible escalates on the hosts it reaches: "
    "it does not need it here."
)
