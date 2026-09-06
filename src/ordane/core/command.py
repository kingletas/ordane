"""Builds the argv for a run, and validates every value before it is used.

A parameter reaches a shell on a remote host, so an unconstrained value is
refused rather than escaped. argv is a list; no string is ever handed to a shell.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from ..presentation.language import MASK
from . import driver as driver_module
from .catalog import SYNTHETIC_ENVIRONMENT, Catalog, Target
from .config import Config, Param

# Conservative by design: a make variable assignment must survive being read
# back by `make`, by bash and by ansible without changing meaning.
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9 ._:@/=+,^$~\[\]{}()<>*?|-]{0,512}$")
_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

ANSIBLE_FLAGS = {
    "check": ["--check"],
    "diff": ["--diff"],
}


class ValidationError(ValueError):
    """A submitted value was rejected."""


# A value shorter than this is not masked: replacing every `a` in a command
# line would destroy the record rather than protect it, and a two-character
# secret is not one.
SHORTEST_MASKABLE = 3


@dataclass(frozen=True)
class Command:
    """What runs, what is recorded, and the values that must not be recorded.

    `argv` is executed. `safe_argv` and `safe_display` are what may be written
    down or shown. Keeping both on one object is what stops a caller from
    recording the first by accident: which is exactly what every caller did.
    """

    argv: list[str]
    display: str
    redact: list[str]

    @classmethod
    def build(cls, argv: list[str], redact: list[str] | None = None) -> Command:
        return cls(argv=argv, display=shlex.join(argv), redact=redact or [])

    @property
    def maskable(self) -> list[str]:
        return [value for value in self.redact if len(value) >= SHORTEST_MASKABLE]

    @property
    def safe_argv(self) -> list[str]:
        return [self.mask(part) for part in self.argv]

    @property
    def safe_display(self) -> str:
        return shlex.join(self.safe_argv)

    def mask(self, text: str) -> str:
        """The same text with every declared secret replaced."""
        for value in self.maskable:
            text = text.replace(value, MASK)
        return text

    def safe_params(self, params: dict[str, str]) -> dict[str, str]:
        return {name: self.mask(value) for name, value in params.items()}


def choices_for(param: Param, catalog: Catalog, repo: Path) -> list[str]:
    """Resolves a parameter's choice list from disk, never from a stored copy."""
    if param.choices:
        return list(param.choices)
    source = param.choices_from
    if not source:
        return []
    if source == "patches":
        return sorted(p.stem for p in (repo / "patches").glob("*.patch"))
    if source == "playbooks":
        return [p.path for p in catalog.playbooks]
    if source == "environments":
        return [e.name for e in catalog.launchable_environments]
    if source.startswith("glob:"):
        pattern = source.removeprefix("glob:")
        return sorted(p.name for p in repo.glob(pattern))
    return []


def validate_environment(catalog: Catalog, name: str) -> str:
    environment = catalog.environment(name)
    if environment is None:
        known = ", ".join(e.name for e in catalog.launchable_environments) or "none"
        raise ValidationError(f"unknown environment {name!r}; known: {known}")
    blocked = environment.blocked_reason
    if blocked:
        raise ValidationError(f"environment {name!r} cannot be used: {blocked}")
    return environment.name


def validate_params(
    target: Target, submitted: dict[str, str], catalog: Catalog, repo: Path
) -> dict[str, str]:
    """Checks every submitted value against the target's declared parameters."""
    accepted: dict[str, str] = {}
    for name, param in target.params.items():
        raw = (submitted.get(name) or "").strip()
        if not raw:
            if param.required:
                raise ValidationError(f"{name} is required")
            continue

        allowed = choices_for(param, catalog, repo)
        if allowed and raw not in allowed:
            if not param.allow_other:
                raise ValidationError(
                    f"{name}={raw!r} is not one of the permitted values: {', '.join(allowed)}"
                )
        if not _SAFE_NAME.match(name):
            raise ValidationError(f"parameter name {name!r} is not permitted")
        if not _SAFE_VALUE.match(raw):
            raise ValidationError(f"{name} contains characters that are not permitted")
        accepted[name] = raw

    unknown = set(submitted) - set(target.params) - {"environment", "dry_run"}
    unknown = {k for k in unknown if (submitted.get(k) or "").strip()}
    if unknown:
        raise ValidationError(f"unknown parameter(s): {', '.join(sorted(unknown))}")
    return accepted


# What a limit and a tag list may hold. Narrower than a parameter value: these
# are Ansible's own selector syntax, and nothing else has any business here.
_SAFE_LIMIT = re.compile(r"^[A-Za-z0-9 ._:!&,*\[\]-]{0,256}$")
_SAFE_TAGS = re.compile(r"^[A-Za-z0-9 ._,-]{0,256}$")

# `-vvvv` is Ansible's own ceiling; more is the same as four.
MAX_VERBOSITY = 4


@dataclass(frozen=True)
class Options:
    """The run options that are not the target's own parameters.

    `--diff` is the one that pairs with `--check`: would this succeed and what would
    this change are different questions.
    """

    diff: bool = False
    limit: str = ""
    tags: str = ""
    verbosity: int = 0

    @property
    def any(self) -> bool:
        return bool(self.diff or self.limit or self.tags or self.verbosity)

    def validated(self) -> Options:
        """Refuses what must not reach a command line, rather than quoting it."""
        if self.limit and not _SAFE_LIMIT.match(self.limit):
            raise ValidationError("the host limit contains characters not permitted")
        if self.tags and not _SAFE_TAGS.match(self.tags):
            raise ValidationError("the tag list contains characters not permitted")
        return Options(
            diff=self.diff,
            limit=self.limit.strip(),
            tags=self.tags.strip(),
            verbosity=max(0, min(int(self.verbosity or 0), MAX_VERBOSITY)),
        )

    @property
    def flags(self) -> list[str]:
        """As Ansible spells them, which is also what a Makefile passes through."""
        found: list[str] = []
        if self.diff:
            found.append("--diff")
        if self.limit:
            found += ["--limit", self.limit]
        if self.tags:
            found += ["--tags", self.tags]
        if self.verbosity:
            found.append("-" + "v" * self.verbosity)
        return found


def for_target(
    *,
    target: Target,
    environment: str,
    params: dict[str, str],
    config: Config,
    dry_run: bool = False,
    catalog: Catalog | None = None,
    options: Options | None = None,
) -> Command:
    """The command this target is, whichever way the repository is driven."""
    options = (options or Options()).validated()
    if target.source:
        return _for_playbook_target(
            target=target,
            environment=environment,
            params=params,
            config=config,
            dry_run=dry_run,
            catalog=catalog,
            options=options,
        )
    return _for_make_target(
        target=target,
        environment=environment,
        params=params,
        config=config,
        dry_run=dry_run,
        options=options,
    )


def _for_playbook_target(
    *,
    target: Target,
    environment: str,
    params,
    config: Config,
    dry_run: bool,
    catalog,
    options: Options | None = None,
) -> Command:
    """`ansible-playbook -i <inventory> <playbook> [-e k=v] [--check]`

    The playbook is never edited to be runnable from here: everything this
    console adds is a flag on the command line.
    """
    inventory = _inventory_for(environment, config, catalog)
    if not inventory:
        raise ValidationError(
            f"no inventory is known for {environment!r}. Set `environments.inventory` in the "
            "configuration, or put the inventory where `environments.discover` looks."
        )
    if not _SAFE_VALUE.match(inventory) or not _SAFE_VALUE.match(target.source):
        raise ValidationError("the inventory or playbook path contains characters not permitted")

    argv = list(config.ansible_command or driver_module.DEFAULT_ANSIBLE_COMMAND)
    argv += ["-i", inventory, target.source]
    for key, value in sorted(params.items()):
        argv += ["-e", f"{key}={value}"]
    if dry_run:
        argv.append("--check")
    argv += (options or Options()).flags
    return Command.build(argv, redact=secret_values(target, params))


def _inventory_for(environment: str, config: Config, catalog) -> str:
    """Where this environment's inventory is, from the catalogue or the template."""
    found = catalog.environment(environment) if catalog is not None else None
    if found is not None and found.inventory:
        return found.inventory
    if config.inventory_template:
        return config.inventory_template.format(environment=environment)
    return ""


def _for_make_target(
    *,
    target: Target,
    environment: str,
    params,
    config: Config,
    dry_run: bool,
    options: Options | None = None,
) -> Command:
    """`make <target> environment=<env> k=v ...`

    A target that names its own environment is launched without the assignment,
    because passing one would be ignored and would misdescribe the run.
    """
    argv = ["make", target.name]
    # A synthetic environment is the stand-in for a control plane that has
    # none, so passing its name would invent a variable the Makefile never reads.
    named = catalog_environment(target, environment)
    if named:
        argv.append(f"{config.environment_var}={named}")
    argv += [f"{k}={v}" for k, v in sorted(params.items())]
    # A Makefile takes them through one variable rather than as flags of its
    # own, which is the convention `EXTRA=--check` already established.
    extra = (["--check"] if dry_run and target.dry_run else []) + (options or Options()).flags
    if extra:
        argv.append("EXTRA=" + " ".join(extra))
    return Command.build(argv, redact=secret_values(target, params))


def secret_values(target: Target, params: dict[str, str]) -> list[str]:
    """The submitted values of every parameter the config marked secret.

    Declaring `secret: true` used to reach one HTML input and nothing else: the
    value went into the command preview, the run index and the output as it was
    typed. This is what the rest of the tool needs to keep it out of them.
    """
    return [
        value
        for name, value in params.items()
        if value and getattr(target.params.get(name), "secret", False)
    ]


def catalog_environment(target: Target, environment: str) -> str:
    """The name to assign, or an empty string when there is nothing to assign."""
    if target.fixed_environment:
        return ""
    if environment == SYNTHETIC_ENVIRONMENT:
        return ""
    return environment


def for_playbook(
    *,
    playbook: str,
    environment: str,
    template: list[str],
    flags: dict[str, bool],
    limit: str = "",
    tags: str = "",
    skip_tags: str = "",
    verbosity: int = 0,
) -> Command:
    """The configured playbook command, then the flags the form selected."""
    if not _SAFE_VALUE.match(playbook):
        raise ValidationError("playbook path contains characters that are not permitted")
    argv = [part.format(playbook=playbook, environment=environment) for part in template]
    for name, enabled in flags.items():
        if enabled and name in ANSIBLE_FLAGS:
            argv += ANSIBLE_FLAGS[name]
    for flag, value in (("--limit", limit), ("--tags", tags), ("--skip-tags", skip_tags)):
        value = (value or "").strip()
        if not value:
            continue
        if not _SAFE_VALUE.match(value):
            raise ValidationError(f"{flag} contains characters that are not permitted")
        argv += [flag, value]
    if verbosity:
        argv.append("-" + "v" * min(int(verbosity), 4))
    return Command.build(argv, redact=[])


def environment_assignment(config: Config, environment: str) -> str:
    return f"{config.environment_var}={environment}"
