"""Checks a control plane and says what to do about anything it finds.

Most of what goes wrong here is silent. An environment misspelt in the allow
list does not raise: it simply never matches, and the console is read-only for
a reason nothing states. A target renamed in the Makefile drops out of its
group without a word. Each check below turns one of those into a sentence.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..presentation.text import plural, sentence
from . import catalog as catalog_module
from . import config as config_module
from . import driver as driver_module
from . import exposure, host, identity, plane
from . import settings as settings_module
from .config import CONFIG_NAME

OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass(frozen=True)
class Finding:
    """One check: what was looked at, how it came out, and what to do next."""

    level: str
    title: str
    detail: str = ""
    fix: str = ""


@dataclass(frozen=True)
class Report:
    findings: list[Finding]

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if f.level == FAIL]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == WARN]

    @property
    def healthy(self) -> bool:
        return not self.failures

    @property
    def headline(self) -> str:
        if self.failures:
            return f"{plural(len(self.failures), 'thing')} the console cannot work around"
        if self.warnings:
            return f"Usable, with {plural(len(self.warnings), 'thing')} worth fixing"
        return "This control plane is in good shape"


def examine(
    repo: Path,
    *,
    history: Path | None = None,
    events: Path | None = None,
    extra: Sequence[Finding] = (),
) -> Report:
    """Everything that can be checked without launching anything.

    `extra` is where a front end adds what only it can answer: whether the
    toolkit it needs is installed, say. This layer knows no front end, so it
    cannot ask on their behalf.
    """
    findings: list[Finding] = []

    if not driver_module.drivable(repo):
        return Report(
            [
                Finding(
                    FAIL,
                    f"{repo} has neither a Makefile nor any playbooks",
                    "There is nothing here to drive.",
                    "Point --repo at the control plane, not at the folder above it.",
                )
            ]
        )

    chosen = driver_module.of(driver_module.choose(repo, _declared_driver(repo)))
    if host.which(chosen.executable) is None:
        return Report(
            [
                Finding(
                    FAIL,
                    f"`{chosen.executable}` is not on PATH",
                    f"This repository is driven by {chosen.name}: {chosen.reason}.",
                    f"Install {chosen.executable}, then run this again.",
                )
            ]
        )

    try:
        config = config_module.load(repo)
    except config_module.ConfigError as exc:
        return Report(
            [
                Finding(
                    FAIL,
                    f"{CONFIG_NAME} cannot be read",
                    str(exc),
                    "Fix the YAML; until then the console cannot start.",
                )
            ]
        )

    findings.append(_running_as(identity.who()))
    findings.append(_config_present(repo))

    try:
        catalog = catalog_module.build(repo, config)
    except catalog_module.CatalogError as exc:
        findings.append(
            Finding(
                FAIL,
                "`make help` could not be read",
                str(exc),
                "Run `make help` in the repository and see what it says.",
            )
        )
        return Report(findings)

    findings.append(_catalogue(catalog))
    findings.append(_how_it_was_read(catalog))
    findings.append(_plane_identity(repo, config))
    findings.append(_launchable(catalog, config))
    findings.append(_how_exposed(catalog))
    findings.extend(_ansible_settings(repo, config))
    findings.extend(_environment_variable(repo, catalog, config))
    findings.extend(_inventories(catalog))
    findings.extend(_names_that_match_nothing(catalog, config))
    findings.extend(_choice_sources(catalog, repo))
    findings.append(_history(history or repo / "docs" / "dora" / "history.csv"))
    findings.append(_events(events))
    findings.extend(extra)
    return Report(findings)


def _ansible_settings(repo: Path, config) -> list[Finding]:
    """What Ansible will be configured by, which is silent in both directions.

    A control plane with no `ansible.cfg` runs on Ansible's defaults and says
    nothing about it, and a declared stdout callback can empty every host
    summary in the history without erroring once.
    """
    declared = config.ansible
    known = settings_module.known_names() if declared else set()
    findings = [_where_ansible_is_configured(repo, declared, known)]

    unknown = sorted(n for n in declared.names if known and n not in known)
    if unknown:
        findings.append(
            Finding(
                WARN,
                f"Ansible does not recognise {sentence(unknown)}",
                "An unrecognised ANSIBLE_* variable is ignored in silence, so the "
                "setting never applies while everything here reports that it did.",
                "Check the spelling against `ansible-config list`.",
            )
        )

    at_risk = declared.recap_at_risk
    if at_risk:
        findings.append(
            Finding(
                WARN,
                f"`{settings_module.RECAP_CALLBACK}` is set to `{at_risk}`",
                "Only Ansible's default callback prints a PLAY RECAP. Without one "
                "this console records no hosts, no per-host counts and no failure "
                "attribution, and nothing about the run reports an error.",
                "Drop the setting, or accept that every run's host summary is empty.",
            )
        )
    return findings


def _where_ansible_is_configured(repo: Path, declared, known) -> Finding:
    """Which config file a run will actually pick up, and what this file adds."""
    own = repo / "ansible.cfg"
    home = Path.home() / ".ansible.cfg"
    where = own if own.is_file() else home if home.is_file() else None
    # Said in the same breath as the count, because an unverified check that
    # stays quiet is indistinguishable from one that passed.
    checked = (
        "Every name is one Ansible knows."
        if known
        else "Ansible could not be asked whether it knows these names."
    )

    if declared and where is not None:
        return Finding(
            OK,
            f"Ansible is configured by {where}",
            f"{CONFIG_NAME} sets {plural(len(declared.names), 'setting')} on top of it: "
            f"{sentence(declared.names)}. {checked}",
        )
    if declared:
        return Finding(
            OK,
            f"Ansible is configured by {CONFIG_NAME} alone",
            f"There is no ansible.cfg here and none in your home directory. "
            f"{plural(len(declared.names), 'setting')} declared: {sentence(declared.names)}. "
            f"Everything else is an Ansible default. {checked}",
        )
    if where is not None:
        return Finding(
            OK, f"Ansible is configured by {where}", "Read from the run's own directory."
        )
    return Finding(
        WARN,
        "This control plane has no ansible.cfg",
        "There is none here and none in your home directory, so every setting is "
        "an Ansible default: no roles path, no inventory plugins beyond the "
        "built-in ones, and no vault password file.",
        f"If a run needs one, declare it under `ansible:` in {CONFIG_NAME}.",
    )


def _declared_driver(repo: Path) -> str:
    """The configured driver, read without failing if the file cannot be."""
    try:
        return config_module.load(repo).driver
    except config_module.ConfigError:
        return ""


def _running_as(actor) -> Finding:
    """Root is not refused and is not passed over quietly either."""
    if not actor.is_root:
        return Finding(OK, f"Running as {actor.name}", "which is what every run is recorded as")
    return Finding(
        FAIL,
        f"Running as root: {actor.summary}",
        identity.ROOT_WARNING,
        "Quit, and start it as the account that owns the control plane.",
    )


def _plane_identity(repo: Path, config) -> Finding:
    """A control plane needs a name a second machine would arrive at too."""
    identified = plane.of(repo, config.control_plane)
    if identified.portable:
        return Finding(OK, f"This control plane is `{identified.name}`", identified.where_from)
    return Finding(
        WARN,
        f"This control plane is only known as `{identified.name}`",
        "That is the folder name. Two people with different checkouts in folders of the "
        "same name would look like one estate in a shared history.",
        f"Add `control_plane: <name>` to {CONFIG_NAME}, or give the repository a git remote.",
    )


def _config_present(repo: Path) -> Finding:
    found = config_module.config_path(repo)
    if found is not None and found.name == CONFIG_NAME:
        return Finding(OK, f"{CONFIG_NAME} is present", str(found))
    if found is not None:
        # Read, so nothing is broken, and named, so the rename is not a thing
        # somebody discovers when a later version stops looking for it.
        return Finding(
            OK,
            f"{found.name} is present, under its former name",
            f"{found} is still read. This file is called {CONFIG_NAME} now.",
            f"Rename it: git mv {found.name} {CONFIG_NAME}",
        )
    return Finding(
        WARN,
        f"There is no {CONFIG_NAME}",
        "The catalogue and the history still work; nothing can be launched.",
        f"Create {repo / CONFIG_NAME} with an `environments.allow` list.",
    )


def _catalogue(catalog) -> Finding:
    if not catalog.targets:
        return Finding(
            FAIL,
            "No targets were found",
            "Three sources were tried: the `Targets:` block `make help` prints, the two "
            "columns it prints, and the `target: ## description` comments in the Makefile.",
            "Add a `## description` comment beside a target: that is the cheapest of the three.",
        )
    where = (
        ""
        if all(e.synthetic for e in catalog.environments)
        else (f", across {plural(len(catalog.environments), 'environment')}")
    )
    return Finding(
        OK,
        f"{plural(len(catalog.targets), 'target')} were found{where}",
    )


def _how_it_was_read(catalog) -> Finding:
    """Which discovery answered. A repository read a different way than its
    owner expects is a confusing thing to debug from the outside."""
    discovery = catalog.discovery
    return Finding(
        OK,
        f"Driven by {discovery.runs_with}",
        f"Targets from {discovery.target_source}; "
        f"environments from {discovery.environment_source}.",
    )


def _environment_variable(repo: Path, catalog, config) -> list[Finding]:
    """Whether anything here looks like it reads the variable the console assigns.

    `make deploy environment=prod` against a control plane that reads `$(env)` does
    not fail: it sets a variable nobody reads and runs against the default.

    A command-line variable is also exported into every recipe, so a control plane
    whose recipes call a script never names it in the Makefile. The finding is
    therefore a warning: this cannot see inside a script.
    """
    # Only `make` is handed a variable. `ansible-playbook` is handed an
    # inventory path, which is a different question and has its own check.
    if catalog.discovery.driver != driver_module.MAKE:
        return []
    if all(e.synthetic for e in catalog.environments):
        return []
    name = config.environment_var
    haystacks = [catalog.help_text]
    for path in [
        repo / "Makefile",
        *sorted(repo.glob("*.mk")),
        *sorted(repo.glob("Makefiles/*.mk")),
    ]:
        if path.is_file():
            try:
                haystacks.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    text = "\n".join(haystacks)

    # `$(name)`, `${name}` or a bare `name=`: the last is how a control plane
    # documents the variable it hands to a script.
    if re.search(rf"\$[({{]{re.escape(name)}[)}}]|\b{re.escape(name)}\s*=", text):
        return []
    others = sorted(set(re.findall(r"\$[({]([A-Za-z_][A-Za-z0-9_]*)[)}]", text)))
    likely = [o for o in others if o.lower() in ("env", "environment", "target_env", "inventory")]
    return [
        Finding(
            WARN,
            f"Nothing here mentions `{name}`",
            f"The console runs `make <target> {name}=<name>`. Neither the Makefiles nor "
            "`make help` name it, though a recipe that passes it to a script would not.",
            f"If a run reaches the wrong place, set `environment_var` in {CONFIG_NAME}"
            + (f": likely {sentence(likely)}." if likely else "."),
        )
    ]


def _how_exposed(catalog) -> Finding:
    """Which environments the console can tell are production, and which it cannot.

    Everything it runs is presented on the strength of this, so an environment
    whose name says nothing is the one place the warning has to be its own.
    """
    launchable = [e.name for e in catalog.launchable_environments]
    if not launchable:
        return Finding(OK, "Nothing may be launched against", "So nothing is exposed.")
    live = [n for n in launchable if exposure.reading(n) == exposure.PRODUCTION]
    unknown = [n for n in launchable if exposure.reading(n) == exposure.UNKNOWN]
    if unknown:
        return Finding(
            WARN,
            f"Nothing in the name says what {sentence(unknown)} is",
            "A run is warned about on the strength of the environment's name, and "
            "these are treated as possibly dangerous because nothing else can be "
            "known about them.",
            "Name it after what it is — production, staging, dev, docker or local — "
            "or accept the warning on every run against it.",
        )
    if live:
        return Finding(
            OK,
            f"{sentence(live)} is treated as production",
            "Every run against it is presented as dangerous, whatever the action is.",
        )
    return Finding(
        OK,
        "Nothing launchable here is production",
        f"{sentence(launchable)} read as safe kinds.",
    )


def _launchable(catalog, config) -> Finding:
    launchable = catalog.launchable_environments
    if launchable:
        return Finding(
            OK,
            f"{plural(len(launchable), 'environment')} may be launched against",
            sentence([e.name for e in launchable]),
        )
    if all(e.synthetic for e in catalog.environments):
        return Finding(
            WARN,
            "Read-only: nothing can be launched",
            "This control plane has no environments, so there is one stand-in to allow.",
            f"Add `allow: [default]` under `environments` in {CONFIG_NAME}.",
        )
    if config.allow_environments:
        return Finding(
            WARN,
            "Every allowed environment is unusable",
            sentence([f"{e.name}: {e.reason}" for e in catalog.environments if not e.usable]),
            "`make help` marks these unusable; the console will not launch against one.",
        )
    return Finding(
        WARN,
        "Read-only: nothing can be launched",
        "No environment is on the allow list.",
        f"Add one under `environments.allow` in {CONFIG_NAME}, or use Manage environments "
        "in the desktop console.",
    )


def _names_that_match_nothing(catalog, config) -> list[Finding]:
    """A name in the config that matches nothing does nothing, and says nothing."""
    findings = []
    # A shortcut is a target `make help` lists on its own line rather than in
    # the target block, so it is a real name even though it is not in the list.
    known_targets = {t.name for t in catalog.targets} | set(config.hidden) | set(catalog.shortcuts)
    known_environments = {e.name for e in catalog.environments}

    ghost_environments = [e for e in config.allow_environments if e not in known_environments]
    if ghost_environments:
        findings.append(
            Finding(
                FAIL,
                "The allow list names an environment `make help` does not print",
                sentence(ghost_environments),
                "A misspelt name never matches, so the console stays read-only silently. "
                f"Known: {sentence(sorted(known_environments))}.",
            )
        )

    grouped = [name for members in config.groups.values() for name in members]
    ghost_targets = sorted(
        {name for name in grouped + list(config.targets) if name not in known_targets}
    )
    if ghost_targets:
        findings.append(
            Finding(
                WARN,
                "The config names targets that no longer exist",
                sentence(ghost_targets),
                "These entries do nothing. Rename or remove them.",
            )
        )

    for name, spec in config.targets.items():
        fixed = str((spec or {}).get("environment", "") or "")
        if fixed and fixed not in known_environments:
            findings.append(
                Finding(
                    FAIL,
                    f"`{name}` declares an environment that does not exist",
                    f"environment: {fixed}",
                    "The allow list would be checked against a name the run never reaches.",
                )
            )
    return findings


def _inventories(catalog) -> list[Finding]:
    """An environment `ansible-playbook` has no inventory for cannot be run against."""
    if catalog.discovery.driver != driver_module.ANSIBLE:
        return []
    missing = [e.name for e in catalog.environments if e.usable and not e.inventory]
    if not missing:
        return []
    return [
        Finding(
            FAIL,
            f"{plural(len(missing), 'environment')} has no inventory",
            sentence(missing),
            "`ansible-playbook` needs a path for `-i`. Set `environments.inventory` in "
            f"{CONFIG_NAME}: `inventory/{{environment}}` is the usual shape, or put the "
            "inventories where `environments.discover` looks.",
        )
    ]


def _choice_sources(catalog, repo: Path) -> list[Finding]:
    """A choice list that resolves to nothing leaves a required field unfillable."""
    findings = []
    for target in catalog.targets:
        for name, param in target.params.items():
            source = param.choices_from
            if not source:
                continue
            from .command import choices_for  # imported here to keep this module import-light

            if not choices_for(param, catalog, repo):
                findings.append(
                    Finding(
                        WARN if not param.required else FAIL,
                        f"`{target.name}` has no values to offer for `{name}`",
                        f"choices_from: {source} matched nothing under {repo}",
                        "The field cannot be filled from the list, so the form is a dead end.",
                    )
                )
    return findings


def _history(path: Path) -> Finding:
    if path.is_file():
        return Finding(OK, "The release history is readable", str(path))
    return Finding(
        WARN,
        "No release history",
        f"Nothing at {path}.",
        "Cadence and lead time have no source until the reporter writes one.",
    )


def _events(path: Path | None) -> Finding:
    if path is None:
        return Finding(WARN, "No deployment event log was named", "", "Pass --events.")
    if path.is_file():
        return Finding(OK, "The deployment event log is readable", str(path))
    if path.parent.is_dir():
        return Finding(
            OK,
            "The deployment event log will be created on the first deploy",
            str(path),
        )
    return Finding(
        WARN,
        "The deployment event log cannot be written yet",
        f"{path.parent} does not exist.",
        "It is created on the first deploy; instrumentation never fails a run.",
    )
