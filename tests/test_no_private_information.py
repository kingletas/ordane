"""Nothing in this repository names the machine it was written on.

This is a published repository, and the things that leak into one are not the
things a reader would think to look for: an absolute home path in a docstring,
a real environment name copied into an example, the author's own login sitting
in a test fixture.

The username and hostname are read at run time rather than written down. A test
that hardcoded them would be the leak it exists to prevent, and this way it
protects whoever runs it rather than whoever wrote it.
"""

from __future__ import annotations

import getpass
import re
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Binary and generated files: a lockfile is full of hashes and a PNG is not text.
SKIP_SUFFIXES = {".png", ".jpg", ".svg", ".zip", ".lock", ".csv"}

# The one home path the documentation is allowed to use, and the author's own
# address, which is published on purpose in the licence and the package.
ALLOWED = ("/home/you", "code@kingletas.com")

# A login shorter than this is a substring of ordinary English.
SHORTEST_CHECKABLE = 4


def tracked_text_files() -> list[Path]:
    """Every tracked text file but this one.

    A scanner that scans itself matches its own patterns and reports them as
    findings. This file carries the patterns and no private information.
    """
    listed = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [
        ROOT / name
        for name in listed
        if Path(name).suffix not in SKIP_SUFFIXES
        and (ROOT / name).is_file()
        and (ROOT / name) != Path(__file__).resolve()
    ]


def offences(pattern: re.Pattern, allow: tuple[str, ...] = ()) -> list[str]:
    found = []
    for path in tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if any(ok in line for ok in allow):
                continue
            if pattern.search(line):
                found.append(f"{path.relative_to(ROOT)}:{number}")
    return found


def test_no_home_directory_but_the_documented_one():
    """`/home/someone` in a docstring says who wrote it and nothing else."""
    assert offences(re.compile(r"/home/[A-Za-z0-9._-]+"), allow=ALLOWED) == []


def test_no_path_into_a_personal_source_tree():
    """`~/Development/thing` is where it lives on one laptop."""
    assert offences(re.compile(r"~/(Development|Documents|Projects|src/[A-Z])")) == []


def identity_shapes(name: str) -> re.Pattern:
    """The forms a login actually leaks in, rather than the bare word.

    Matching the word alone assumes a login is never ordinary English. On a GitHub
    runner it is `runner`, which this codebase says on nearly every page.
    """
    escaped = re.escape(name)
    return re.compile(rf"(/home/{escaped}|~{escaped}/|\b{escaped}@)")


def test_the_login_running_this_is_not_written_down_anywhere():
    """Read rather than hardcoded, so this protects the reader, not the author."""
    login = getpass.getuser()
    if len(login) < SHORTEST_CHECKABLE:
        return
    assert offences(identity_shapes(login), allow=ALLOWED) == []


def test_this_machines_name_is_not_written_down_anywhere():
    """A hostname leaks as `someone@here` or on its own, and unlike a login it
    is rarely a word, so the bare match is safe enough to keep."""
    host = socket.gethostname().split(".")[0]
    if len(host) < SHORTEST_CHECKABLE:
        return
    assert offences(re.compile(rf"\b{re.escape(host)}\b"), allow=ALLOWED) == []


def test_the_checks_can_actually_fail():
    """A scan that matches nothing proves nothing about the tree."""
    assert offences(re.compile(r"/home/[A-Za-z0-9._-]+")) != [], (
        "the documented /home/you should be found when it is not allowed"
    )


def test_the_narrowed_login_check_still_catches_a_real_leak(tmp_path):
    """Narrowing it to identity shapes must not narrow it into uselessness."""
    pattern = identity_shapes("ada")
    assert pattern.search('PATH_HERE = "/home/ada/control-plane"')
    assert pattern.search("actor was ada@thinkpad")
    assert pattern.search("look in ~ada/bin")
    # And the false positive that failed CI: the word on its own.
    assert not pattern.search("the ada runs on a thread")
