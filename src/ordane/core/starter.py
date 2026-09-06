"""Writes a first `.ordane.yml` for a repository, from what was found in it.

Somebody pointing the console at their own control plane for the first time
should not have to read a reference to get past read-only. This writes a file
naming the targets and environments that are actually there, with everything
that is a judgement left commented out: because a starter that guesses which
targets are dangerous would be worse than one that asks.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import driver as driver_module
from .catalog import Catalog
from .config import CONFIG_NAME

# The variables a Makefile is likely to be reading for "where does this run".
LIKELY_VARIABLES = ("environment", "env", "target_env", "inventory", "stage")

# A target worth using as the commented example, most interesting first.
EXAMPLE_ORDER = ("deploy", "release", "activate", "cutover", "rollback", "apply")


class StarterExists(FileExistsError):
    """There is already a configuration file, and it is not this tool's to replace."""


def environment_variable(repo: Path) -> str:
    """Which variable the Makefile actually reads, or the default if it reads none."""
    makefile = repo / "Makefile"
    if not makefile.is_file():
        return "environment"
    try:
        text = makefile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "environment"
    used = {name.lower() for name in re.findall(r"\$[({]([A-Za-z_][A-Za-z0-9_]*)[)}]", text)}
    for candidate in LIKELY_VARIABLES:
        if candidate in used:
            return candidate
    return "environment"


def _example_target(catalog: Catalog) -> str:
    names = [t.name for t in catalog.targets]
    for wanted in EXAMPLE_ORDER:
        if wanted in names:
            return wanted
    return names[0] if names else "deploy"


def render(repo: Path, catalog: Catalog) -> str:
    """The file, as a person would want to read it on the day they open it."""
    real = [e for e in catalog.environments if not e.synthetic]
    variable = environment_variable(repo)
    example = _example_target(catalog)

    ansible = catalog.discovery.driver == driver_module.ANSIBLE
    supplies = (
        "The playbooks supply the targets and their names, and the inventories the environments."
        if ansible
        else "`make help` supplies the targets, their descriptions and the environments."
    )
    lines = [
        f"# {CONFIG_NAME}: a starting point, written by `ordane init`.",
        "#",
        f"# {supplies}",
        "# This file carries what they cannot say: which environments this console",
        "# may reach, what a parameter means, and which runs count as a release.",
        "#",
        "# Nothing outside this file is ever written. The playbooks are read.",
        "#",
        f"# The console read {len(catalog.targets)} target(s) from "
        f"{catalog.discovery.target_source}.",
        "",
        "environments:",
        "  # Nothing runs until a name is here, and an empty list is where this",
        "  # starts on purpose. Uncomment one when you mean it.",
        "  allow: []",
    ]

    if real:
        lines.append(f"  # Found in {catalog.discovery.environment_source}:")
        lines += [f"  #   - {environment.name}" for environment in real]
    else:
        lines += [
            "  # This control plane has no environments of its own, so there is one",
            "  # stand-in: `allow: [default]` lets its targets run with no assignment.",
        ]

    lines += (
        [
            "",
            "  # Where an environment's inventory is, when it is not one of the above.",
            "  # `{environment}` is substituted.",
            "  # inventory: inventory/{environment}",
            "",
            "# This repository has no Makefile, so a run is",
            "#   ansible-playbook -i <inventory> <playbook>",
            "# Name something else here if that is wrapped in a script of your own.",
            "# ansible_command: [ansible-playbook]",
            "",
        ]
        if ansible
        else [
            "",
            "# The variable a target reads to know where it runs. The console assigns this one",
            "# and nothing else, so a Makefile reading a different name would be handed a value",
            "# nobody looks at.",
            f"environment_var: {variable}",
            "",
        ]
    )
    lines += [
        "# The order these are declared in is the order the console shows them.",
        "# groups:",
        f"#   Release: [{example}]",
        "",
        "# What the repository cannot say about one target.",
        "# targets:",
        f"#   {example}:",
        "#     danger: high            # low | medium | high",
        "#     confirm: type-environment-name",
        "#     deploy: true            # counts towards the delivery measures",
        "#     params:",
        "#       branch_name:",
        "#         help: the branch to build",
        "#         allow_other: true",
        "",
    ]
    return "\n".join(lines)


def write(repo: Path, catalog: Catalog, *, force: bool = False) -> Path:
    """Writes the starter, refusing to overwrite a file somebody else authored."""
    path = repo / CONFIG_NAME
    if path.exists() and not force:
        raise StarterExists(f"{path} already exists")
    path.write_text(render(repo, catalog), encoding="utf-8")
    return path
