"""Derives the action surface from the target repository, never from a stored copy.

A control plane is not obliged to look like the one this was written for. Three
ways of finding targets are tried in turn and three of finding environments,
and the catalogue records which one answered so the interface can say so.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..presentation import ansi
from . import driver as driver_module
from . import host, makeparams

# `make help` in both control-plane repositories prints the same three blocks.
_TARGET_LINE = re.compile(r"^ {2}([A-Za-z0-9][A-Za-z0-9_.-]*): (.+)$")
_ENV_LINE = re.compile(r"^ {2}(\S+)(?:\s{2,}\((.+)\))?\s*$")
_ENV_HEADING = re.compile(r"^Environments\b.*:?\s*$")
_TARGET_HEADING = re.compile(r"^Targets:\s*$")
_SHORTCUT_HEADING = re.compile(r"^Shortcuts:\s*(.*)$")

MAKE_TIMEOUT_SECONDS = 30


class CatalogError(RuntimeError):
    """The target repository could not be read."""


@dataclass(frozen=True)
class Target:
    name: str
    description: str
    group: str = "Other"
    danger: str = "low"
    params: dict = field(default_factory=dict)
    dry_run: bool = False
    fixed_environment: str = ""
    # The playbook this runs, for a repository driven without a Makefile.
    # Empty when the target is a make target.
    source: str = ""


@dataclass(frozen=True)
class Environment:
    name: str
    usable: bool
    reason: str = ""
    allowed: bool = True
    # True for the stand-in used when a control plane has no environments at
    # all: a run against it passes no environment assignment.
    synthetic: bool = False
    # The inventory this environment is, when it was found as one on disk.
    # `ansible-playbook` needs a path; `make` needs only the name.
    inventory: str = ""

    @property
    def blocked_reason(self) -> str:
        """Why this environment cannot be launched against, or an empty string."""
        if not self.usable:
            return self.reason or "unusable"
        if not self.allowed:
            return "not in the allow list"
        return ""


@dataclass(frozen=True)
class Playbook:
    path: str
    label: str


# How each half of the catalogue was found, in a sentence, because a repository
# read a different way than its owner expects is a confusing thing to debug.
TARGET_SOURCES = {
    "make-help-block": "the `Targets:` block that `make help` prints",
    "make-help-columns": "the two columns that `make help` prints",
    "makefile-comments": "the `## description` comments in the Makefile",
    "playbooks": "the playbooks on disk, named by the first play in each",
    "none": "nothing: no targets were found",
}

ENVIRONMENT_SOURCES = {
    "make-help": "the environment block that `make help` prints",
    "directories": "the inventory directories on disk",
    "none": "nothing: this control plane has no environments of its own",
}

# Where an environment lives when `make help` does not list them. Directories
# first, because an inventory is usually one; a file is taken by its stem.
DEFAULT_ENVIRONMENT_GLOBS = (
    "inventory/*",
    "inventories/*",
    "environments/*",
    "inventory/*.yml",
    "inventories/*.yml",
)

# The environment a control plane gets when it has none: a run against it
# carries no assignment, and it still has to be allowed before anything runs.
SYNTHETIC_ENVIRONMENT = "default"


@dataclass(frozen=True)
class Discovery:
    """Which strategy answered for each half, so the interface can report it."""

    targets: str = "none"
    environments: str = "none"
    driver: str = driver_module.MAKE

    @property
    def runs_with(self) -> str:
        return driver_module.of(self.driver).name

    @property
    def target_source(self) -> str:
        return TARGET_SOURCES.get(self.targets, self.targets)

    @property
    def environment_source(self) -> str:
        return ENVIRONMENT_SOURCES.get(self.environments, self.environments)


@dataclass(frozen=True)
class Catalog:
    targets: list[Target]
    environments: list[Environment]
    playbooks: list[Playbook]
    shortcuts: list[str]
    discovery: Discovery = field(default_factory=Discovery)
    # Kept so the doctor can look for evidence in it rather than running
    # `make help` a second time for the same answer.
    help_text: str = ""

    def target(self, name: str) -> Target | None:
        return next((t for t in self.targets if t.name == name), None)

    def environment(self, name: str) -> Environment | None:
        return next((e for e in self.environments if e.name == name), None)

    def playbook(self, path: str) -> Playbook | None:
        return next((p for p in self.playbooks if p.path == path), None)

    @property
    def launchable_environments(self) -> list[Environment]:
        return [e for e in self.environments if e.usable and e.allowed]


def run_make_help(repo: Path) -> str:
    """Returns `make help` with its colour removed, or raises.

    A help target that colours its own output is still a help target, so the
    escapes come off before anything tries to read columns out of it.
    """
    return ansi.strip(_run_make_help(repo))


def _run_make_help(repo: Path) -> str:
    try:
        result = subprocess.run(
            host.argv(["make", "help"]),
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=MAKE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CatalogError("make is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise CatalogError(f"`make help` timed out after {MAKE_TIMEOUT_SECONDS}s") from exc
    if result.returncode != 0:
        raise CatalogError(f"`make help` failed in {repo}: {result.stderr.strip()}")
    return result.stdout


def parse_make_help(text: str) -> tuple[list[Target], list[Environment], list[str]]:
    """Splits `make help` into its targets, environments and shortcuts."""
    targets: list[Target] = []
    environments: list[Environment] = []
    shortcuts: list[str] = []
    section = None

    for line in text.splitlines():
        if _ENV_HEADING.match(line):
            section = "env"
            continue
        if _TARGET_HEADING.match(line):
            section = "target"
            continue
        shortcut_match = _SHORTCUT_HEADING.match(line)
        if shortcut_match:
            section = None
            shortcuts = shortcut_match.group(1).split()
            continue
        if not line.strip():
            section = None
            continue

        if section == "target":
            match = _TARGET_LINE.match(line)
            if match:
                targets.append(Target(name=match.group(1), description=match.group(2).strip()))
        elif section == "env":
            match = _ENV_LINE.match(line)
            if match:
                flagged = match.group(2) is not None
                environments.append(
                    Environment(
                        name=match.group(1),
                        usable=not flagged,
                        reason=_tidy_reason(match.group(2) or ""),
                    )
                )

    return targets, environments, shortcuts


# The two-column shape every `grep '## '` help target prints:
#     deploy          Deploy the application
# Two or more spaces separate the name from the description, which is what
# distinguishes it from the block dialect's `name: description`.
_COLUMN_LINE = re.compile(r"^ {2,}([A-Za-z0-9][A-Za-z0-9_.-]*) {2,}(\S.*?)\s*$")

# The convention the two-column help target reads in the first place. Matched
# against the Makefile itself, so it works even when `help` does something else.
_COMMENT_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:[^=]*?##\s+(\S.*?)\s*$")


def parse_help_columns(text: str) -> list[Target]:
    """Targets from a help target that prints two columns rather than a block.

    Only used when there is no `Targets:` heading: with one, the environment
    block sits in the same output and would be read as targets.
    """
    if _has_target_heading(text):
        return []
    targets = []
    for line in text.splitlines():
        match = _COLUMN_LINE.match(line)
        if match:
            targets.append(Target(name=match.group(1), description=match.group(2)))
    return targets


def _has_target_heading(text: str) -> bool:
    return any(_TARGET_HEADING.match(line) for line in text.splitlines())


def parse_makefile_comments(repo: Path) -> list[Target]:
    """Targets from `target: ## description` in the Makefile and any `*.mk` beside it."""
    targets: dict[str, Target] = {}
    for path in [repo / "Makefile", *sorted(repo.glob("*.mk"))]:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            match = _COMMENT_LINE.match(line)
            if match:
                targets.setdefault(
                    match.group(1), Target(name=match.group(1), description=match.group(2))
                )
    return list(targets.values())


def inventory_for(repo: Path, name: str, globs) -> str:
    """The path an environment named by `make help` has on disk, if it has one.

    Discovery records where it found an environment; a name printed by `make help`
    arrives without one, and the same globs answer both.
    """
    if not name or "/" in name or name.startswith("."):
        return ""
    for pattern in globs:
        head = pattern.rsplit("/", 1)[0]
        for candidate in (repo / head / name, repo / head / f"{name}.yml"):
            try:
                inside = candidate.resolve().relative_to(repo.resolve())
            except (OSError, ValueError):
                continue
            if candidate.exists():
                return inside.as_posix()
    return ""


def discover_environments(repo: Path, globs) -> list[Environment]:
    """Environments from the inventory directories, when `make help` lists none.

    The path comes back with the name: a run driven by `ansible-playbook` needs
    an inventory to point `-i` at, and guessing it later from the name would
    reintroduce the assumption this replaced.
    """
    found: dict[str, Environment] = {}
    for pattern in globs:
        for path in sorted(repo.glob(pattern)):
            name = path.name if path.is_dir() else path.stem
            if name.startswith(".") or name in found:
                continue
            found[name] = Environment(
                name=name, usable=True, inventory=path.relative_to(repo).as_posix()
            )
    return list(found.values())


# The `- name:` on the first play, which is the nearest thing a playbook has to
# the `## description` comment a Makefile carries. Read, never written.
_PLAY_NAME = re.compile(r"^\s*-\s+name:\s*(.+?)\s*$")


def playbook_targets(repo: Path, globs: list[str]) -> list[Target]:
    """Targets from the playbooks themselves, for a repository with no Makefile."""
    targets: dict[str, Target] = {}
    for playbook in discover_playbooks(repo, globs):
        name = Path(playbook.path).stem
        if name in targets:
            # Two playbooks with the same stem: the path is what tells them
            # apart, so that is the name rather than one silently winning.
            name = playbook.path
        targets[name] = Target(
            name=name,
            description=first_play_name(repo / playbook.path) or playbook.path,
            source=playbook.path,
        )
    return list(targets.values())


def first_play_name(path: Path) -> str:
    """The first play's name, read line by line rather than parsed.

    A playbook can carry Jinja that no YAML loader will accept out of context,
    and this only ever needs one line of it.
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("#") or not line.strip() or line.startswith("---"):
                    continue
                match = _PLAY_NAME.match(line)
                return match.group(1).strip("\"'") if match else ""
    except OSError:
        return ""
    return ""


# A YAML file in the repository root that is configuration, not a play.
NOT_A_PLAYBOOK = frozenset({"requirements.yml", "galaxy.yml", ".ordane.yml", "meta.yml"})


# `make help` writes its own verdict into the reason, e.g. "no inventory --
# unusable". The interface already says the environment cannot be used.
_TRAILING_VERDICT = re.compile(r"\s*[-–—]{1,2}\s*(unusable|not usable|cannot be used)\s*$", re.I)


def _tidy_reason(text: str) -> str:
    return _TRAILING_VERDICT.sub("", text.strip()).strip()


def discover_playbooks(repo: Path, globs: list[str]) -> list[Playbook]:
    """Lists the playbooks on disk that the configured globs select."""
    seen: dict[str, Playbook] = {}
    for pattern in globs:
        for path in sorted(repo.glob(pattern)):
            if not path.is_file() or path.name in NOT_A_PLAYBOOK:
                continue
            relative = path.relative_to(repo).as_posix()
            seen.setdefault(relative, Playbook(path=relative, label=relative))
    return list(seen.values())


def _params_for(name: str, config, documented: dict) -> dict:
    """Declared parameters, over the ones the Makefile documents for itself.

    A console that could only offer a form for a target somebody had written
    down twice would be a config file with a window on it.
    """
    from .config import Param

    params = {
        found.name: Param(name=found.name, required=found.required, example=found.example)
        for found in documented.get(name, {}).values()
    }
    params.update(config.params_for(name))
    return params


def build(repo: Path, config) -> Catalog:  # noqa: ANN001 - config is a Config, imported lazily
    """Reads the repository and returns everything the interface can offer.

    Each half is looked for in more than one place, because a control plane
    written by somebody else is not obliged to print what this one expects.
    """
    found, discovery, help_text = _discover(repo, config)
    targets, environments, shortcuts = found
    documented = makeparams.read(repo, config.environment_var)

    targets = [
        Target(
            name=t.name,
            description=t.description,
            group=config.group_for(t.name),
            danger=config.danger_for(t.name),
            params=_params_for(t.name, config, documented),
            dry_run=config.supports_dry_run(t.name) or bool(t.source),
            fixed_environment=config.fixed_environment(t.name),
            source=t.source,
        )
        for t in targets
        if not config.is_hidden(t.name)
    ]

    environments = [
        Environment(
            name=e.name,
            usable=e.usable,
            reason=e.reason,
            allowed=config.environment_allowed(e.name),
            synthetic=e.synthetic,
            inventory=e.inventory or inventory_for(repo, e.name, config.environment_globs),
        )
        for e in environments
    ]

    return Catalog(
        targets=targets,
        environments=environments,
        playbooks=discover_playbooks(repo, config.playbook_globs),
        shortcuts=shortcuts,
        discovery=discovery,
        help_text=help_text,
    )


def _discover(repo: Path, config) -> tuple[tuple[list, list, list], Discovery, str]:
    """Targets and environments, from whichever source answers first."""
    chosen = driver_module.choose(repo, config.driver)
    if chosen == driver_module.ANSIBLE:
        return _discover_playbooks(repo, config, chosen)

    help_text, help_failure = _help_or_reason(repo)
    targets, environments, shortcuts = parse_make_help(help_text)
    target_source = "make-help-block" if targets else ""
    environment_source = "make-help" if environments else ""

    if not targets:
        targets = parse_help_columns(help_text)
        target_source = "make-help-columns" if targets else ""
    if not targets:
        targets = parse_makefile_comments(repo)
        target_source = "makefile-comments" if targets else "none"
    if not targets:
        # Every route has been tried, so the help failure is the real reason
        # rather than something that could be worked around.
        raise CatalogError(
            help_failure
            or "no targets found: `make help` printed none and the Makefile has no "
            "`target: ## description` comments"
        )

    if not environments:
        environments = discover_environments(repo, config.environment_globs)
        environment_source = "directories" if environments else ""
    declared = _declared_environments(config, {e.name for e in environments})
    if declared:
        environments += declared
        environment_source = environment_source or "config"
    if not environments:
        environments = [Environment(name=SYNTHETIC_ENVIRONMENT, usable=True, synthetic=True)]
        environment_source = "none"

    return (
        (targets, environments, shortcuts),
        Discovery(targets=target_source, environments=environment_source, driver=chosen),
        help_text,
    )


def _discover_playbooks(repo: Path, config, chosen: str):
    """A repository with no Makefile: the playbooks are the action surface."""
    globs = (
        config.playbook_globs
        if config.playbooks_declared
        else list(driver_module.DEFAULT_PLAYBOOK_GLOBS)
    )
    targets = playbook_targets(repo, globs)
    if not targets:
        raise CatalogError(
            f"no playbooks found under {', '.join(globs)}, and there is no Makefile: "
            "point `playbooks:` in the configuration at where they are"
        )
    environments = discover_environments(repo, config.environment_globs)
    source = "directories" if environments else ""
    declared = _declared_environments(config, {e.name for e in environments})
    environments += declared
    if declared and not source:
        source = "config"
    if not environments:
        environments = [Environment(name=SYNTHETIC_ENVIRONMENT, usable=True, synthetic=True)]
        source = "none"
    return (
        (targets, environments, []),
        Discovery(targets="playbooks", environments=source, driver=chosen),
        "",
    )


def _declared_environments(config, already: set[str]) -> list[Environment]:
    """Names the configuration states outright, for an inventory nothing finds."""
    return [
        Environment(
            name=name,
            usable=True,
            inventory=config.inventory_template.format(environment=name)
            if config.inventory_template
            else "",
        )
        for name in config.environment_names
        if name not in already
    ]


def _help_or_reason(repo: Path) -> tuple[str, str]:
    """`make help`, or an empty string and why it could not be run.

    A repository with no `help` target is not unreadable: its Makefile still
    carries the comments the convention is built on, so this reports rather
    than raises, and only the total absence of targets is fatal.
    """
    try:
        return run_make_help(repo), ""
    except CatalogError as exc:
        if "make is not on PATH" in str(exc):
            raise
        return "", str(exc)
