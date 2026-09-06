"""Every file the examples need has to survive a clone."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str) -> set[str]:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return {line for line in done.stdout.splitlines() if line}


def test_no_example_file_is_left_untracked() -> None:
    """An ignored example file is present here and absent for everyone else.

    A global excludes file applies to every repository under a home directory, and a
    bare pattern such as `docker` or `production` matches an inventory by name.
    """
    tracked = _git("ls-files", "examples")
    on_disk = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "examples").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    missing = sorted(on_disk - tracked)
    assert not missing, (
        "these example files exist here and would not survive a clone: " + ", ".join(missing)
    )
