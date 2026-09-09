"""The shape of a run: one lane per host, one cell per task.

Ansible already prints what every host did to every task — `ok:`, `changed:`,
`skipping:`, `fatal:` — and then throws that away into a recap of totals. This
reads it back into a grid, which is the one thing a log cannot show: which
hosts are lagging, and which task is the slow one.

It reads the same buffer while a run is live, so the grid fills in as the run
goes rather than appearing when it ends.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_TASK = re.compile(r"^(?:TASK|HANDLER)\s+\[(?P<name>.*?)\]\s*\**\s*$")
_PLAY = re.compile(r"^PLAY\s+\[(?P<name>.*?)\]\s*\**\s*$")
_RECAP = re.compile(r"^PLAY RECAP\b")

# `ok: [web-01]`, `changed: [web-01] => (item=…)`, `fatal: [web-01]: FAILED!`.
_RESULT = re.compile(
    r"^(?P<state>ok|changed|skipping|skipped|failed|fatal|unreachable|rescued|ignoring)"
    r":\s*\[(?P<host>[^\]]+?)(?:\s*->\s*[^\]]+)?\]"
)

# `ansible` answering a question of a host group, which prints no task headers.
_ASKED = re.compile(
    r"^(?P<host>[^\s|]+)\s*\|\s*(?P<state>SUCCESS|CHANGED|FAILED|UNREACHABLE|SKIPPED)!?\b"
)

OK = "ok"
CHANGED = "changed"
SKIPPED = "skipped"
FAILED = "failed"
RUNNING = "running"
PENDING = "pending"

_FROM_ANSIBLE = {
    "ok": OK,
    "changed": CHANGED,
    "skipping": SKIPPED,
    "skipped": SKIPPED,
    "failed": FAILED,
    "fatal": FAILED,
    "unreachable": FAILED,
    "rescued": CHANGED,
    "ignoring": OK,
}

_FROM_ASKED = {
    "SUCCESS": OK,
    "CHANGED": CHANGED,
    "FAILED": FAILED,
    "UNREACHABLE": FAILED,
    "SKIPPED": SKIPPED,
}

# How many tasks a grid draws before it starts folding the middle away. Past
# this each cell is thinner than the gap between them and the shape stops
# being readable, which is the only thing the grid is for.
MAX_TASKS = 14

# And how many hosts. A run against a hundred hosts is read by its recap.
MAX_HOSTS = 24

# A cell state ranks over another when both are reported for one task, which a
# loop does once per item. One failed item makes the cell failed.
_RANK = {PENDING: 0, SKIPPED: 1, OK: 2, CHANGED: 3, FAILED: 4}


@dataclass
class Grid:
    """Which hosts did what to which tasks, in the order the run printed them."""

    tasks: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    cells: dict[tuple[str, str], str] = field(default_factory=dict)
    # The task the run is on. Empty once the recap has been printed.
    current: str = ""
    hidden_tasks: int = 0
    hidden_hosts: int = 0

    @property
    def known(self) -> bool:
        return bool(self.tasks and self.hosts)

    def state(self, host: str, task: str, live: bool = False) -> str:
        """One cell. A live run's current task is `running` where nothing landed yet."""
        found = self.cells.get((host, task))
        if found is not None:
            return found
        if live and task == self.current:
            return RUNNING
        return PENDING

    @property
    def done(self) -> int:
        """How many tasks every host has finished, which is what `4 / 6` counts."""
        return sum(
            1 for task in self.tasks if all((host, task) in self.cells for host in self.hosts)
        )


def read(output: str) -> Grid:
    """Builds the grid from a run's captured output, however far it has got."""
    grid = Grid()
    task = ""
    in_recap = False
    tasks: list[str] = []
    hosts: list[str] = []
    cells: dict[tuple[str, str], str] = {}

    for raw in (output or "").splitlines():
        line = _ANSI.sub("", raw).rstrip()

        if _RECAP.match(line):
            in_recap = True
            task = ""
            continue
        if in_recap:
            # The recap is totals, and the grid is not made of totals.
            continue
        if _PLAY.match(line):
            continue

        found = _TASK.match(line)
        if found:
            task = _unique(found.group("name"), tasks)
            tasks.append(task)
            continue

        result = _RESULT.match(line)
        if result and task:
            host = result.group("host")
            if host not in hosts:
                hosts.append(host)
            state = _FROM_ANSIBLE.get(result.group("state"), OK)
            _keep(cells, host, task, state)
            continue

        asked = _ASKED.match(line)
        if asked:
            # A question asked of a group is one column: the question itself.
            if not tasks:
                tasks.append("answered")
            host = asked.group("host")
            if host not in hosts:
                hosts.append(host)
            _keep(cells, host, tasks[0], _FROM_ASKED.get(asked.group("state"), OK))

    grid.current = "" if in_recap else task
    grid.tasks, grid.hidden_tasks = _trim(tasks, MAX_TASKS, keep_last=True)
    grid.hosts, grid.hidden_hosts = _trim(hosts, MAX_HOSTS, keep_last=False)
    grid.cells = {
        key: value for key, value in cells.items() if key[0] in grid.hosts and key[1] in grid.tasks
    }
    return grid


def _keep(cells: dict, host: str, task: str, state: str) -> None:
    """The worst thing a host did to a task, because a loop reports once an item."""
    at = (host, task)
    if _RANK[state] >= _RANK.get(cells.get(at, PENDING), 0):
        cells[at] = state


def _unique(name: str, seen: list[str]) -> str:
    """Two tasks with the same name are two columns, not one that keeps changing."""
    if name not in seen:
        return name
    index = 2
    while f"{name} ({index})" in seen:
        index += 1
    return f"{name} ({index})"


def _trim(names: list[str], ceiling: int, keep_last: bool) -> tuple[list[str], int]:
    """Cuts a run of names down to what can be drawn, and says how many were cut.

    Tasks keep the newest, because a live run's front edge is what is being
    watched. Hosts keep the first, because their order is the inventory's.
    """
    if len(names) <= ceiling:
        return list(names), 0
    kept = names[-ceiling:] if keep_last else names[:ceiling]
    return kept, len(names) - ceiling
