"""What is actually inside an environment, asked of Ansible rather than guessed.

An environment is a name and a path to point `-i` at, which is enough to run
something and not enough to say what it will touch.

Reading the inventory answers that before the run: a deploy that builds on one
host and activates on several can say which builder it used, which is the
difference between knowing what you are about to do and not.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Aliased: this module iterates over hosts, and `host` is a loop variable here.
from . import host as host_module

# A dynamic inventory calls out to a cloud API, so this is generous. It runs on
# a thread and its answer is cached; what it must never do is hang a window.
TIMEOUT_SECONDS = 30

# Bookkeeping groups Ansible always reports. `all` repeats every host and
# `ungrouped` is a hole rather than a role.
NOT_A_ROLE = ("all", "ungrouped")

# `ansible-inventory` exits 0 when an inventory plugin fails. It prints a
# warning, returns a valid empty inventory, and reports success, so a dynamic
# inventory that could not authenticate is indistinguishable, by exit code and
# by output, from one that genuinely holds nothing. The difference is the whole
# question, and it is only in the warning.
COULD_NOT_PARSE = "Failed to parse"

# Ansible wraps its warnings at the terminal width, so the sentence that says
# why is split across lines. This finds the reason it gives after naming the
# plugin, which is the only part of four warnings worth reading.
WHY = re.compile(r"Failed to parse .*? with \S+ plugin:\s*(.+?)(?=\[WARNING\]|$)", re.S)


@dataclass(frozen=True)
class Group:
    """One role in an environment, with every host under it and its children."""

    name: str
    hosts: tuple[str, ...] = ()

    @property
    def one_host(self) -> str:
        return self.hosts[0] if len(self.hosts) == 1 else ""


@dataclass(frozen=True)
class Inventory:
    """What Ansible says an inventory holds, or why it could not say."""

    groups: tuple[Group, ...] = ()
    error: str = ""
    hint: str = ""

    @property
    def known(self) -> bool:
        return bool(self.groups) and not self.error

    @property
    def hosts(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for group in self.groups:
            for host in group.hosts:
                seen.setdefault(host, None)
        return tuple(seen)

    def group(self, name: str) -> Group | None:
        return next((one for one in self.groups if one.name == name), None)


def read(repo: Path, inventory: str, extra: list[str] | None = None) -> Inventory:
    """Asks `ansible-inventory` what is in there. Never raises into a caller."""
    if not inventory:
        return Inventory(error="This environment has no inventory to read.")
    argv = ["ansible-inventory", "--list", "-i", inventory, *(extra or [])]
    try:
        result = subprocess.run(
            host_module.argv(argv),
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return Inventory(
            error="ansible-inventory is not on the PATH.",
            hint="It comes with Ansible. Without it this console cannot look inside an inventory.",
        )
    except subprocess.TimeoutExpired:
        return Inventory(
            error=f"ansible-inventory did not answer in {TIMEOUT_SECONDS} seconds.",
            hint="A dynamic inventory that asks a cloud API can take this long.",
        )
    except OSError as exc:
        return Inventory(error="ansible-inventory could not be run.", hint=str(exc))

    if result.returncode != 0:
        # Its stderr carries the reason, and it is Ansible's own words rather
        # than this console's guess at them.
        return Inventory(error="Ansible could not read that inventory.", hint=_tail(result.stderr))
    return parse(result.stdout, result.stderr)


def parse(text: str, complaints: str = "") -> Inventory:
    """Turns `--list` output into groups, with every child's hosts folded in.

    `complaints` is whatever Ansible printed while doing it. An inventory plugin
    that failed says so there and nowhere else.
    """
    try:
        raw = json.loads(text or "{}")
    except (ValueError, TypeError):
        return Inventory(error="That inventory did not come back as JSON.")
    if not isinstance(raw, dict):
        return Inventory(error="That inventory did not come back as JSON.")

    groups = {
        name: value
        for name, value in raw.items()
        if name != "_meta" and isinstance(value, dict | list)
    }
    found = [
        Group(name=name, hosts=tuple(_hosts_of(name, groups, set())))
        for name in sorted(groups)
        if name not in NOT_A_ROLE
    ]
    kept = [one for one in found if one.hosts]
    refused = COULD_NOT_PARSE in (complaints or "")
    if not kept:
        # Empty and complained about is a failure; empty and quiet is empty.
        # Reporting the first as the second is how a console says a fleet has
        # no hosts because nobody could log in to ask.
        if refused:
            return Inventory(
                error="Ansible could not read that inventory.",
                hint=_why(complaints),
            )
        return Inventory(error="That inventory holds no hosts.")
    if refused:
        # Some of it answered. What did not is still worth saying.
        return Inventory(groups=tuple(kept), hint=_why(complaints))
    return Inventory(groups=tuple(kept))


def _hosts_of(name: str, groups: dict, seen: set[str]) -> list[str]:
    """A group's own hosts plus its children's, without going round a cycle."""
    if name in seen:
        return []
    seen.add(name)
    entry = groups.get(name)
    if isinstance(entry, list):
        return list(entry)
    if not isinstance(entry, dict):
        return []
    hosts = list(entry.get("hosts") or [])
    for child in entry.get("children") or []:
        for host in _hosts_of(child, groups, seen):
            if host not in hosts:
                hosts.append(host)
    return hosts


def _tail(text: str, lines: int = 3) -> str:
    kept = [line for line in (text or "").splitlines() if line.strip()]
    return " ".join(kept[-lines:])[:400]


def _why(text: str) -> str:
    """Ansible's own reason a plugin refused, or the last of what it printed."""
    unwrapped = " ".join((text or "").split())
    found = WHY.search(unwrapped)
    if not found:
        return _tail(text)
    return found.group(1).strip()[:400]
