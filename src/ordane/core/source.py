"""Where a control plane comes from: cloning it, fetching it, changing its ref.

Everything else in this package reads a checkout and never writes one. These
four operations do, so they are here rather than beside the status line in
`repository.py`, and each of them reports what went wrong instead of raising
into an interface.

**Choosing a ref is choosing everything.** The Makefile, the playbooks, the
inventory and `.ordane.yml` all come from the tree at the checked-out
ref, so a branch can widen the list of environments this console will launch
against. That is inherent: it is what `git checkout` has always meant, and it
is why nothing here switches a ref quietly.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import host

# Long enough for a real clone over a slow link, short enough that a hung git
# does not hold an interface for ever.
CLONE_TIMEOUT = 300
QUERY_TIMEOUT = 20

# The transports a control plane may be fetched over. Everything else is
# refused by name, and `ext::` is the reason this is a list rather than a
# pattern: `git clone ext::sh -c whoami` runs a command of the URL's choosing,
# so an unrecognised scheme is a refusal and never a try. `file://` and an
# absolute path are here because neither can name a command, and a control
# plane on a mounted share is a real place for one to live.
SCHEMES = ("https://", "http://", "ssh://", "git://", "file://")

# `git@github.com:owner/repo.git`, which is a URL with no scheme in it.
_SCP_LIKE = re.compile(r"^[A-Za-z0-9_.+-]+@[A-Za-z0-9_.-]+:[^\s]+$")

# What a directory may be called, so a name taken from a URL cannot climb out
# of the folder it is being written into. The dot is allowed inside a name and
# never as the whole of one: `..` matches every character class you would write
# for this, and is the one name that must not be accepted.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_NOT_A_NAME = {".", ".."}


@dataclass(frozen=True)
class Outcome:
    """What happened, and what to say about it. Never an exception."""

    ok: bool
    message: str = ""
    detail: str = ""

    @property
    def failed(self) -> bool:
        return not self.ok


@dataclass(frozen=True)
class Ref:
    """One thing that can be checked out, and enough of it to choose by."""

    name: str
    kind: str
    commit: str = ""
    subject: str = ""
    when: str = ""
    current: bool = False

    @property
    def is_remote(self) -> bool:
        return self.kind == "remote"


def usable_url(url: str) -> Outcome:
    """Whether this is a URL git may be pointed at, decided by allowing rather than blocking."""
    text = (url or "").strip()
    if not text:
        return Outcome(False, "No URL given.")
    if text.startswith("-"):
        return Outcome(False, "A URL cannot start with a dash: git would read it as a flag.")
    if any(character.isspace() for character in text):
        return Outcome(False, "A URL cannot contain spaces.")
    if _SCP_LIKE.match(text):
        return Outcome(True)
    if text.startswith(SCHEMES) or text.startswith("/"):
        return Outcome(True)
    return Outcome(
        False,
        "Only https, ssh, git and file URLs, or an absolute path, are accepted.",
        "Other transports let a URL choose a command to run, so they are refused rather "
        "than tried.",
    )


def folder_for(url: str) -> str:
    """The directory a URL is cloned into: its last segment, and nothing else."""
    tail = (url or "").rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    tail = tail.removesuffix(".git")
    if tail in _NOT_A_NAME or not _SAFE_NAME.match(tail):
        return ""
    return tail


def clone(url: str, parent: Path, name: str = "") -> Outcome:
    """Clones into `parent/name`, using whatever credentials git already has.

    Nothing here asks for a password or stores one: git's own credential
    helper and ssh agent are what authenticate, exactly as they do at a prompt.
    """
    allowed = usable_url(url)
    if allowed.failed:
        return allowed
    folder = name or folder_for(url)
    if not folder:
        return Outcome(False, "That URL does not end in a name a folder can be called.")
    into = parent / folder
    if into.exists():
        return Outcome(False, f"{into} already exists.", "Open it instead, or move it aside.")
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return Outcome(False, f"{parent} could not be created.", str(exc))

    # `--` so a URL is never read as a flag, however it got here.
    done = _git(parent, "clone", "--", url, folder, timeout=CLONE_TIMEOUT)
    if done.failed:
        return Outcome(False, "The clone failed.", done.detail)
    return Outcome(True, f"Cloned into {into}", str(into))


def fetch(repo: Path) -> Outcome:
    """Brings the remote's refs up to date. Changes nothing that is checked out."""
    done = _git(repo, "fetch", "--prune", timeout=CLONE_TIMEOUT)
    return Outcome(True, "Fetched") if done.ok else Outcome(False, "The fetch failed.", done.detail)


def refs(repo: Path) -> list[Ref]:
    """Every branch and tag, local and remote, newest first. Empty outside git.

    The full refname leads the line, because it is what says whether a ref is a
    branch, a tag or a remote, and `%(HEAD)` trails it, because git omits the
    tab before an empty last field and a tag's is always empty.
    """
    listed = _git(
        repo,
        "for-each-ref",
        "--sort=-committerdate",
        "--format=%(refname)%09%(objectname:short)%09%(committerdate:short)%09"
        "%(contents:subject)%09%(HEAD)",
        "refs/heads",
        "refs/remotes",
        "refs/tags",
    )
    if listed.failed:
        return []
    found: list[Ref] = []
    for line in listed.detail.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        full, commit, when, subject = parts[:4]
        head = parts[4] if len(parts) > 4 else ""
        # `refs/remotes/origin/HEAD` is a pointer at the default branch, not a
        # branch. It shortens to a bare `origin`, which reads as one.
        if full.endswith("/HEAD"):
            continue
        found.append(
            Ref(
                name=_short(full),
                kind=_kind_of(full),
                commit=commit,
                subject=subject,
                when=when,
                current=head.strip() == "*",
            )
        )
    return found


def _short(full: str) -> str:
    for prefix in ("refs/heads/", "refs/remotes/", "refs/tags/"):
        if full.startswith(prefix):
            return full[len(prefix) :]
    return full


def _kind_of(full: str) -> str:
    if full.startswith("refs/remotes/"):
        return "remote"
    return "tag" if full.startswith("refs/tags/") else "branch"


def switch(repo: Path, ref: str) -> Outcome:
    """Checks out a ref, and refuses rather than discarding anything uncommitted.

    A remote branch is checked out as a local one tracking it, which is what
    somebody choosing `origin/release` means by choosing it.
    """
    if not ref or ref.startswith("-"):
        return Outcome(False, "That is not a ref.")
    dirty = _git(repo, "status", "--porcelain")
    if dirty.ok and dirty.detail.strip():
        return Outcome(
            False,
            "There are uncommitted changes here.",
            "Switching would carry them onto another ref or lose them. Commit or stash "
            "them first: this console will not decide that for you.",
        )
    local = ref.split("/", 1)[1] if ref.startswith("origin/") else ref
    if ref.startswith("origin/") and _git(repo, "rev-parse", "--verify", local).failed:
        done = _git(repo, "checkout", "-b", local, "--track", ref)
    else:
        done = _git(repo, "checkout", local if ref.startswith("origin/") else ref)
    if done.failed:
        return Outcome(False, f"Could not switch to {ref}.", done.detail)
    return Outcome(True, f"On {local}")


def _git(repo: Path, *arguments: str, timeout: int = QUERY_TIMEOUT) -> Outcome:
    try:
        result = subprocess.run(
            host.argv(["git", *arguments]),
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Outcome(False, "git timed out", f"`git {arguments[0]}` did not finish")
    except OSError as exc:
        return Outcome(False, "git could not be run", str(exc))
    if result.returncode != 0:
        return Outcome(False, "git refused", (result.stderr or result.stdout).strip())
    return Outcome(True, detail=result.stdout.strip())
