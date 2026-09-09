"""Runs one `make` target or playbook in a pty and streams what it prints.

A pty is used because Ansible only colours its output when it sees a terminal.
Nothing here ever builds a shell string: argv is a list, always.
"""

from __future__ import annotations

import errno
import os
import pty
import re
import selectors
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from queue import Empty, Queue

from ..core import config as config_module
from ..core import host, identity, repository
from ..core.command import Command
from . import dora
from .lock import Locked, Locks
from .redact import Redactor
from .store import Run, RunStore, new_id, now
from .summary import from_asked
from .summary import parse as parse_summary

# The kind a question asked of hosts is recorded under. It runs `ansible`
# rather than a playbook, and answers a line at a time rather than in a recap.
PROBE = "probe"

READ_SIZE = 65536
POLL_SECONDS = 0.25
TERM_GRACE_SECONDS = 10


class RunnerError(RuntimeError):
    """The run could not be started."""


class ActiveRun:
    """A running child process, its stored record, and its output queue."""

    def __init__(
        self,
        run: Run,
        store: RunStore,
        redactor: Redactor,
        events_path: Path | None = None,
        on_finish=None,
    ) -> None:
        self.run = run
        self._store = store
        self._redactor = redactor
        self._events_path = events_path
        # Called however the run ends, including when it is cancelled or the
        # process never started: whatever it releases must not be left held.
        self._on_finish = on_finish or (lambda: None)
        self._queue: Queue[str | None] = Queue()
        self._buffer: list[str] = []
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        # The pty this run is talking through, kept so a prompt can be
        # answered, and the prompt it is waiting on if it is waiting on one.
        self._primary = -1
        self._asking = ""

    @property
    def id(self) -> str:
        return self.run.id

    @property
    def finished(self) -> bool:
        return self.run.state != "running"

    def buffered(self) -> str:
        with self._lock:
            return "".join(self._buffer)

    def cancel(self) -> bool:
        """Signals the process group, then kills it if it does not stop."""
        process = self._process
        if process is None or process.poll() is not None:
            return False
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGINT)
        except (ProcessLookupError, PermissionError):
            return False
        self.run.state = "cancelled"
        return True

    def stream(self) -> Iterator[str]:
        """Yields output already seen, then each new chunk until the run ends."""
        yield self.buffered()
        while True:
            try:
                chunk = self._queue.get(timeout=POLL_SECONDS)
            except Empty:
                if self.finished:
                    return
                yield ""
                continue
            if chunk is None:
                return
            yield chunk

    def _emit(self, text: str) -> None:
        with self._lock:
            self._buffer.append(text)
        self._queue.put(text)

    def start(self, argv: list[str], cwd: Path, env: dict[str, str]) -> None:
        primary, secondary = pty.openpty()
        self._primary = primary
        try:
            self._process = subprocess.Popen(  # noqa: S603
                # On the host when this is a flatpak, and unchanged otherwise.
                # What is recorded stays the command the operator asked for:
                # the spawn wrapper is how it ran, not what was run.
                host.argv(argv),
                cwd=cwd,
                env=env,
                stdin=secondary,
                stdout=secondary,
                stderr=secondary,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            os.close(primary)
            os.close(secondary)
            raise RunnerError(f"could not start {argv[0]}: {exc}") from exc
        os.close(secondary)
        threading.Thread(
            target=self._pump, args=(primary,), name=f"run-{self.run.id}", daemon=True
        ).start()

    @property
    def asking(self) -> str:
        """The prompt this run is waiting on, or nothing.

        A playbook run with `--ask-vault-pass` could not be run from here at
        all: it sat on a prompt nobody could see and nothing could answer.
        """
        return self._asking

    def answer(self, secret: str) -> bool:
        """Types a secret into the run, and teaches the redactor never to print it.

        The value goes to the process and nowhere else: not to the store, not
        to the output, not to the record. It is masked from here on because
        Ansible echoes some of what it is given.
        """
        if self._primary < 0 or not self._asking:
            return False
        self._redactor.also(secret)
        try:
            os.write(self._primary, (secret + "\n").encode("utf-8"))
        except OSError:
            return False
        self._asking = ""
        return True

    def _pump(self, primary: int) -> None:
        started = time.monotonic()
        pending = ""
        selector = selectors.DefaultSelector()
        selector.register(primary, selectors.EVENT_READ)
        try:
            while True:
                for _ in selector.select(timeout=POLL_SECONDS):
                    try:
                        data = os.read(primary, READ_SIZE)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            data = b""
                        else:
                            raise
                    if not data:
                        raise _StreamClosed
                    pending += data.decode("utf-8", errors="replace")
                    *lines, pending = pending.split("\n")
                    if lines:
                        self._emit("".join(self._redactor.line(x) + "\n" for x in lines))
                    # A prompt has no newline after it, so it is whatever is
                    # left over: which is the only way to notice one.
                    self._asking = _prompt_in(pending)
                if self._process is not None and self._process.poll() is not None:
                    try:
                        remainder = os.read(primary, READ_SIZE)
                    except OSError:
                        remainder = b""
                    if not remainder:
                        raise _StreamClosed
                    pending += remainder.decode("utf-8", errors="replace")
        except _StreamClosed:
            pass
        finally:
            selector.close()
            if pending:
                self._emit(self._redactor.line(pending) + "\n")
            self._asking = ""
            self._primary = -1
            os.close(primary)
            self._finish(started)

    def _finish(self, started: float) -> None:
        """Everything a run does when it ends, with the release guaranteed.

        Whatever fails in here: a disk that will not take the output, a recap
        that will not parse: the lock is dropped and the queue is closed. A
        lock held by a run that has finished is the worst of both.
        """
        try:
            self._conclude(started)
        finally:
            self._on_finish()
            self._queue.put(None)

    def _conclude(self, started: float) -> None:
        process = self._process
        code = None
        if process is not None:
            try:
                code = process.wait(timeout=TERM_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait()

        self.run.exit_code = code
        self.run.duration_s = round(time.monotonic() - started, 2)
        self.run.finished = now()
        if self.run.state != "cancelled":
            self.run.state = "succeeded" if code == 0 else "failed"

        captured = self.buffered()
        # A question asked of a host group prints no `PLAY RECAP`; its answer
        # is one line per host, so it is read a different way or not at all.
        read = from_asked(captured) if self.run.kind == PROBE else parse_summary(captured)
        self.run.summary = read.as_record()
        self._store.output_path(self.run.id).write_text(captured, encoding="utf-8")
        self._store.append(self.run)
        if self._events_path is not None:
            dora.emit_finish(self.run, self._events_path)


# What Ansible asks for, spelled as it spells it. Deliberately not a bare
# `password:`, a playbook that prints one would put the interface into a
# state nothing had asked for.
_PROMPT = re.compile(
    r"(?im)^(?:.*?\s)??((?:vault|become|sudo|ssh|bastion)\s+password[^:\n]*)\s*:\s*$"
)


def _prompt_in(pending: str) -> str:
    """The prompt a run is sitting on, from the text with no newline after it."""
    if not pending.strip():
        return ""
    found = _PROMPT.search(pending)
    return found.group(1).strip() + ":" if found else ""


class _StreamClosed(Exception):
    """The pty reached end of file."""


class Runner:
    """Owns the active runs and refuses to start a second one per environment."""

    def __init__(
        self,
        store: RunStore,
        repo: Path,
        events_path: Path | None = None,
        plane: str = "",
        lock_scope: str = "",
    ) -> None:
        self._store = store
        self._repo = repo
        self._events_path = events_path
        self._plane = plane
        self._locks = Locks(store.root, lock_scope)
        self._runs: dict[str, ActiveRun] = {}
        self._lock = threading.Lock()

    def get(self, run_id: str) -> ActiveRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def active(self) -> list[ActiveRun]:
        with self._lock:
            return [r for r in self._runs.values() if not r.finished]

    def busy_with(self, environment: str, target: str = "") -> object | None:
        """Whoever is already running this, in any console on any machine.

        It used to look only at this process's own runs, so two windows could
        both deploy the same environment and neither noticed.
        """
        return self._locks.held_by(self._plane, environment, target)

    def anyone_running(self):
        """Whoever is running against this control plane, from any console."""
        return self._locks.anyone_holding(self._plane)

    def start(
        self,
        *,
        kind: str,
        name: str,
        environment: str,
        params: dict[str, str],
        command: Command,
        labels: dict[str, str] | None = None,
        builder: str = "",
        sequence: str = "",
        origin: str = "hand",
    ) -> ActiveRun:
        """Starts a run, or raises if that environment is already busy.

        The actor is read from the process rather than from `$USER`, which anybody can
        set and which under `sudo` commonly still names who you were before.

        It takes the whole command rather than an argv and a string separately, because a
        caller handed those apart can record the one with the secrets in it.
        """
        actor = identity.who()
        started = now()
        try:
            self._locks.take(
                plane=self._plane,
                environment=environment,
                target=name,
                actor=actor,
                started=started,
            )
        except Locked as held:
            raise RunnerError(str(held)) from held

        # Both read at launch, which is the only moment either is true of this
        # run. Taking the settings here rather than from a caller is what stops
        # an edited config being ignored until the window is restarted.
        checkout = repository.read(self._repo)
        declared = config_module.load_quietly(self._repo).ansible

        # What is recorded is the masked twin; what is executed is not.
        run = Run(
            id=new_id(),
            kind=kind,
            name=name,
            environment=environment,
            repo=str(self._repo),
            plane=self._plane,
            host=actor.host,
            installation=identity.installation(self._store.root),
            params=command.safe_params(params),
            argv=command.safe_argv,
            command=command.safe_display,
            actor=actor.name,
            started=started,
            branch=checkout.branch,
            commit=checkout.commit,
            dirty=checkout.dirty,
            builder=builder,
            sequence=sequence,
            origin=origin,
            settings=dict(declared.values),
            labels=labels or {},
        )
        release = lambda: self._locks.release(self._plane, environment, name)  # noqa: E731
        active = ActiveRun(
            run, self._store, Redactor(command.redact), self._events_path, on_finish=release
        )
        self._store.append(run)
        if self._events_path is not None:
            dora.emit_start(run, self._events_path)

        env = dict(os.environ)
        env["ANSIBLE_FORCE_COLOR"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        # A run talks through a pty, so anything that pages waits for a keypress
        # that can never arrive: `ansible-config dump` and `ansible-doc` both
        # do. There is nobody at this terminal, so no run may ever page.
        env["PAGER"] = "cat"
        env["GIT_PAGER"] = "cat"
        # The plane wins over the console's own two: a declaration nothing
        # honours is worse than one that was never read.
        env = declared.applied_to(env)
        try:
            active.start(command.argv, self._repo, env)
        except Exception:
            # A run that never started still took the lock.
            release()
            raise

        with self._lock:
            self._runs[run.id] = active
        return active
