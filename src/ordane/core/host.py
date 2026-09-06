"""Running a command on the machine, from wherever this console happens to be.

Installed from a package or a checkout, a command runs directly. Installed as a
flatpak it cannot: `make`, `ansible`, `git` and `docker` live on the host, and
the sandbox has none of them. A flatpak that could not reach them would open,
read nothing and offer nothing, which is worse than not shipping one.

So everything that spawns goes through here, and inside a sandbox it is handed
to `flatpak-spawn --host`. That is a large permission and it is the honest one:
this application exists to run commands you already run.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path

# Written into every flatpak sandbox by the runtime. Its presence is the
# documented way to know you are in one.
SANDBOX_MARKER = Path("/.flatpak-info")

SPAWN = "flatpak-spawn"
HOST = (SPAWN, "--host")

# Long enough for `command -v` on a busy machine, short enough that a broken
# portal cannot hold a window open.
LOOKUP_SECONDS = 10


def sandboxed() -> bool:
    """True when this is running inside a flatpak."""
    return SANDBOX_MARKER.is_file()


def argv(command: list[str]) -> list[str]:
    """The command as it must actually be spawned from here."""
    if not sandboxed():
        return list(command)
    return [*HOST, *command]


@functools.lru_cache(maxsize=64)
def which(name: str) -> str | None:
    """Where a command is, asked of the machine that will run it.

    `shutil.which` answers about the sandbox, which is the wrong question when
    the command will be spawned on the host. Cached because the doctor asks
    about the same handful of executables repeatedly.
    """
    if not sandboxed():
        return shutil.which(name)
    if shutil.which(SPAWN) is None:
        return None
    try:
        found = subprocess.run(  # noqa: S603
            [*HOST, "sh", "-c", f"command -v {name}"],
            capture_output=True,
            text=True,
            timeout=LOOKUP_SECONDS,
            check=False,
            env=dict(os.environ),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    path = found.stdout.strip().splitlines()
    return path[0] if found.returncode == 0 and path else None
