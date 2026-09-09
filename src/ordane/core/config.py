"""Reads `.ordane.yml`, which carries what `make help` cannot express."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import runbook as runbook_module
from . import settings as settings_module
from . import validation as validation_module

CONFIG_NAME = ".ordane.yml"

# What this file was called before the project was named. A control plane
# somebody already wrote one for keeps working, and the doctor says which of
# the two it read: a console that silently found no config is a console that
# reports an empty catalogue and no reason for it.
FORMER_CONFIG_NAME = ".ansible-gui.yml"

DANGER_LEVELS = ("low", "medium", "high")

# Nothing is launchable until the config names it. An empty allow list means
# the console is read-only, which is the safe state to fail into.
DEFAULT_ALLOW_ENVIRONMENTS: list[str] = []

DEFAULT_PLAYBOOK_GLOBS = ["actions/*.yml", "playbooks/*/playbook.yml"]

# Where an environment lives when `make help` does not list them. Overridable,
# because an inventory can be anywhere a repository decides to put it.
DEFAULT_ENVIRONMENT_GLOBS = [
    "inventory/*",
    "inventories/*",
    "environments/*",
    "inventory/*.yml",
    "inventories/*.yml",
]

# How a bare playbook is run. {playbook} and {environment} are substituted;
# every other element is passed through as-is.
DEFAULT_PLAYBOOK_COMMAND = ["bin/run-playbook", "{playbook}"]


class ConfigError(ValueError):
    """The configuration file is present but unusable."""


@dataclass(frozen=True)
class Param:
    name: str
    required: bool = False
    choices: list[str] = field(default_factory=list)
    choices_from: str = ""
    allow_other: bool = False
    help: str = ""
    secret: bool = False
    # What a real value looks like, shown as the field's placeholder. Read from
    # the `# make <target> key=value` line a Makefile already carries.
    example: str = ""

    @property
    def constrained(self) -> bool:
        """True when the value can only come from a list this tool controls."""
        return bool(self.choices or self.choices_from) and not self.allow_other


@dataclass(frozen=True)
class Config:
    allow_environments: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOW_ENVIRONMENTS))
    groups: dict[str, list[str]] = field(default_factory=dict)
    targets: dict[str, dict[str, Any]] = field(default_factory=dict)
    hidden: list[str] = field(default_factory=list)
    playbook_globs: list[str] = field(default_factory=lambda: list(DEFAULT_PLAYBOOK_GLOBS))
    # Whether `playbooks:` was written down. The default set is this estate's
    # shape, and a repository driven by ansible-playbook needs a wider one —
    # but only where nobody has said where the playbooks are.
    playbooks_declared: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)
    slos: list[dict[str, Any]] = field(default_factory=list)
    environment_var: str = "environment"
    environment_globs: list[str] = field(default_factory=lambda: list(DEFAULT_ENVIRONMENT_GLOBS))
    # Environments this file declares outright, for a control plane whose
    # inventories are somewhere nothing here would look.
    environment_names: list[str] = field(default_factory=list)
    # Where an environment's inventory is, when the name alone was declared.
    # `{environment}` is substituted.
    inventory_template: str = ""
    # `make` or `ansible`; empty means whichever the repository looks like.
    driver: str = ""
    # What this control plane is called in a shared history. Declared, because
    # a folder name is not portable and a git remote is not always there.
    control_plane: str = ""
    # `target`: two people may run different runbooks against one environment,
    # but not the same one. `environment` locks the whole environment instead.
    lock_scope: str = "target"
    ansible_command: list[str] = field(default_factory=list)
    # `ansible` rather than `ansible-playbook`: a question to a host group is
    # not a playbook, and a control plane may wrap either.
    ansible_probe_command: list[str] = field(default_factory=list)
    # The image and the checks a control plane runs against itself.
    validation: validation_module.Suite = field(default_factory=validation_module.Suite)
    # The task whose output says which notifications a run got through. Named
    # rather than guessed: nothing here decides which line of a playbook's
    # output matters.
    notifications_task: str = ""
    playbook_command: list[str] = field(default_factory=lambda: list(DEFAULT_PLAYBOOK_COMMAND))
    # What this plane declares about Ansible itself, for one with no
    # ansible.cfg of its own. Applied as environment variables, which
    # compose with any config file rather than replacing it.
    ansible: settings_module.Settings = field(default_factory=settings_module.Settings)

    @property
    def metric_environments(self) -> list[str]:
        """Which environments count towards a delivery measure; empty means all."""
        return [str(e) for e in (self.metrics.get("environments") or [])]

    def environment_allowed(self, name: str) -> bool:
        return name in self.allow_environments

    def is_hidden(self, target: str) -> bool:
        return target in self.hidden

    def group_for(self, target: str) -> str:
        for group, members in self.groups.items():
            if target in members:
                return group
        return "Other"

    @property
    def group_order(self) -> list[str]:
        """The order the config declared, which is a decision rather than a listing."""
        return [*self.groups, "Other"]

    def sort_groups(self, names) -> list[str]:
        """Declared groups first, in their own order; anything else after, alphabetically."""
        order = self.group_order
        known = [n for n in order if n in names]
        return known + sorted(n for n in names if n not in order)

    def danger_for(self, target: str) -> str:
        level = str(self.targets.get(target, {}).get("danger", "low"))
        return level if level in DANGER_LEVELS else "low"

    def supports_dry_run(self, target: str) -> bool:
        return bool(self.targets.get(target, {}).get("dry_run", False))

    def fixed_environment(self, target: str) -> str:
        """A shortcut target names its own environment, so the allow list must use that."""
        return str(self.targets.get(target, {}).get("environment", "") or "")

    def confirm_mode(self, target: str) -> str:
        return str(self.targets.get(target, {}).get("confirm", ""))

    def labels_for(self, target: str) -> dict[str, str]:
        """What a run of this target counts as: a deploy, a cutover, both or neither.

        The config owns what its own keys mean, so everything that records a
        run agrees about which ones a delivery measure may count.
        """
        spec = self.targets.get(target, {}) or {}
        labels = {}
        if spec.get("deploy"):
            labels["deploy"] = "true"
        if spec.get("cutover"):
            labels["cutover"] = "true"
        return labels

    def runbook_for(self, target: str) -> runbook_module.Runbook:
        """The operational half of a target: who owns it, what proves it, what undoes it."""
        return runbook_module.read(target, self.targets.get(target, {}) or {})

    def used_by(self, target: str) -> list[runbook_module.Use]:
        """Which other runbooks lean on this target."""
        return runbook_module.used_by(self.targets, target)

    def params_for(self, target: str) -> dict[str, Param]:
        raw = self.targets.get(target, {}).get("params", {}) or {}
        return {name: _param(name, spec) for name, spec in raw.items()}


def _param(name: str, spec: Any) -> Param:
    if spec is None:
        return Param(name=name)
    if not isinstance(spec, dict):
        raise ConfigError(f"param {name!r} must be a mapping, got {type(spec).__name__}")
    return Param(
        name=name,
        required=bool(spec.get("required", False)),
        choices=[str(c) for c in spec.get("choices", []) or []],
        choices_from=str(spec.get("choices_from", "") or ""),
        allow_other=bool(spec.get("allow_other", False)),
        help=str(spec.get("help", "") or ""),
        secret=bool(spec.get("secret", False)),
        example=str(spec.get("example", "") or ""),
    )


def _settings(raw: Any) -> settings_module.Settings:
    """The declared Ansible settings, reported as a config problem like any other."""
    try:
        return settings_module.read(raw)
    except settings_module.SettingsError as exc:
        raise ConfigError(str(exc)) from exc


def config_path(repo: Path) -> Path | None:
    """The config this repository carries, under either name, or nothing.

    The current name wins where a repository somehow has both: a file somebody
    wrote today outranks one left from before the rename.
    """
    for name in (CONFIG_NAME, FORMER_CONFIG_NAME):
        found = repo / name
        if found.is_file():
            return found
    return None


def load_quietly(repo: Path) -> Config:
    """The config, or the defaults, for a caller that must not fail on bad YAML.

    A window has to open before it can tell anybody the file is broken.
    """
    try:
        return load(repo)
    except ConfigError:
        return Config()


def load(repo: Path) -> Config:
    """Loads the repository's config, returning defaults when there is none."""
    path = config_path(repo)
    if path is None:
        return Config()

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")

    environments = raw.get("environments", {}) or {}
    if not isinstance(environments, dict):
        raise ConfigError("`environments` must be a mapping")

    return Config(
        allow_environments=[str(e) for e in environments.get("allow", []) or []],
        environment_globs=[str(g) for g in environments.get("discover", []) or []]
        or list(DEFAULT_ENVIRONMENT_GLOBS),
        environment_names=[str(e) for e in environments.get("names", []) or []],
        inventory_template=str(environments.get("inventory", "") or ""),
        driver=str(raw.get("driver", "") or ""),
        control_plane=str(raw.get("control_plane", "") or ""),
        lock_scope=str(raw.get("lock", "target") or "target"),
        ansible_command=[str(part) for part in raw.get("ansible_command", []) or []],
        ansible_probe_command=[str(part) for part in raw.get("ansible_probe_command", []) or []],
        validation=validation_module.read(raw.get("validation")),
        ansible=_settings(raw.get("ansible")),
        notifications_task=str((raw.get("notifications") or {}).get("task", "") or ""),
        groups={str(k): [str(v) for v in vs or []] for k, vs in (raw.get("groups") or {}).items()},
        targets=raw.get("targets") or {},
        hidden=[str(h) for h in raw.get("hidden", []) or []],
        playbook_globs=[str(g) for g in raw.get("playbooks", []) or []] or DEFAULT_PLAYBOOK_GLOBS,
        playbooks_declared=bool(raw.get("playbooks")),
        metrics=dict(raw.get("metrics") or {}),
        slos=list(raw.get("slos") or []),
        environment_var=str(raw.get("environment_var", "environment")),
        playbook_command=[str(p) for p in raw.get("playbook_command", []) or []]
        or list(DEFAULT_PLAYBOOK_COMMAND),
    )
