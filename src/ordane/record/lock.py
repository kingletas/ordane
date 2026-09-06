"""One lock per thing being run, held on disk so two consoles can see it.

A lock in memory is invisible to a second window, or to a second machine sharing
a state directory, so this one is a file.

The key is the control plane, the environment and the target, so two people
running different runbooks against one environment is allowed and two running
the same one is not. `lock: environment` takes the whole environment instead.

Work is handed to the lock rather than the lock to the work: `holding()` wraps a
block and releases in a `finally`, so a release cannot be forgotten or skipped by
an exception. An asynchronous run gets the same guarantee from a `finally` around
everything it does when it ends.

Releasing never raises. Turning the end of a failed run into a second failure
helps nobody, and the next console to look finds the holder gone and clears it.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# What the lock covers, and the two answers a control plane may give.
BY_TARGET = "target"
BY_ENVIRONMENT = "environment"
SCOPES = (BY_TARGET, BY_ENVIRONMENT)

DIRECTORY = "locks"

# A key becomes a filename, so it may only be these.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class Holder:
    """Who holds a lock, said well enough that the answer is actionable."""

    actor: str
    target: str
    environment: str
    started: str
    pid: int
    host: str = ""

    @property
    def elsewhere(self) -> bool:
        """Whether this is another machine, where the pid means nothing here."""
        from ..core import identity

        return bool(self.host) and self.host != identity.who().host

    def describe(self) -> str:
        where = f" on {self.host}" if self.elsewhere else ""
        return f"{self.actor} started {self.target} on {self.environment} at {self.started}{where}"


class Locked(RuntimeError):
    """Somebody else is already running this."""

    def __init__(self, holder: Holder) -> None:
        super().__init__(holder.describe())
        self.holder = holder


class Locks:
    """The lock directory. One file per key, holding who has it."""

    def __init__(self, root: Path, scope: str = BY_TARGET) -> None:
        self.root = Path(root) / DIRECTORY
        self.scope = scope if scope in SCOPES else BY_TARGET

    def key(self, plane: str, environment: str, target: str) -> str:
        parts = [plane, environment] + ([target] if self.scope == BY_TARGET else [])
        return _UNSAFE.sub("-", "--".join(p for p in parts if p)) or "unnamed"

    def path(self, plane: str, environment: str, target: str) -> Path:
        return self.root / f"{self.key(plane, environment, target)}.json"

    def held_by(self, plane: str, environment: str, target: str) -> Holder | None:
        """Who holds this lock, or None: releasing it if the holder is gone."""
        path = self.path(plane, environment, target)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            holder = Holder(**{k: v for k, v in record.items() if k in Holder.__annotations__})
        except (OSError, ValueError, TypeError):
            return None
        if holder.elsewhere:
            # Another machine's process, which this one cannot ask about. The
            # lock stands: a stale lock is an inconvenience, and clearing one
            # that is not stale is a second deploy.
            return holder
        if _alive(holder.pid):
            return holder
        path.unlink(missing_ok=True)
        return None

    def anyone_holding(self, plane: str) -> Holder | None:
        """Anybody running against this control plane, whichever console started it.

        `held_by` answers about one key. This answers the different question a
        ref switch has to ask: is anything at all running out of this tree,
        including from a window this process cannot see.
        """
        prefix = _UNSAFE.sub("-", plane)
        try:
            files = sorted(self.root.glob("*.json"))
        except OSError:
            return None
        for path in files:
            if not path.name.startswith(prefix):
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                holder = Holder(**{k: v for k, v in record.items() if k in Holder.__annotations__})
            except (OSError, ValueError, TypeError):
                continue
            if holder.elsewhere or _alive(holder.pid):
                return holder
            path.unlink(missing_ok=True)
        return None

    def take(self, *, plane: str, environment: str, target: str, actor, started: str) -> Path:
        """Takes the lock, or raises `Locked` naming who has it.

        The file is created with `O_EXCL`, so two consoles arriving together
        cannot both believe they got it.
        """
        held = self.held_by(plane, environment, target)
        if held is not None:
            raise Locked(held)
        path = self.path(plane, environment, target)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = json.dumps(
            {
                "actor": actor.name,
                "host": actor.host,
                "target": target,
                "environment": environment,
                "started": started,
                "pid": os.getpid(),
            }
        )
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError as exc:
            # Somebody took it between the check and the open, which is the
            # race the exclusive create exists to lose rather than ignore.
            held = self.held_by(plane, environment, target)
            if held is None:
                raise
            raise Locked(held) from exc
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(record)
        return path

    def release(self, plane: str, environment: str, target: str) -> bool:
        """Drops the lock. Never raises, and says whether it managed it.

        A release that fails is the end of a run that has already gone wrong,
        and raising here would replace the real failure with this one. The lock
        left behind names a process that has gone, so the next console clears it.
        """
        try:
            self.path(plane, environment, target).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("could not release the lock on %s/%s: %s", plane, environment, exc)
            return False
        return True

    @contextmanager
    def holding(
        self, *, plane: str, environment: str, target: str, actor, started: str
    ) -> Iterator[None]:
        """Runs a block under the lock, and releases it however the block ends.

        For work that finishes where it started. A run does not: it carries on
        in a thread, so the runner takes the lock itself and releases it in the
        `finally` that ends every run.
        """
        self.take(plane=plane, environment=environment, target=target, actor=actor, started=started)
        try:
            yield
        finally:
            self.release(plane, environment, target)


def _alive(pid: int) -> bool:
    """Whether a process on this machine is still there."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
