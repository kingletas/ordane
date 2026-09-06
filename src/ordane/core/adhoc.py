"""Asking hosts a question, without giving them an instruction.

AWX runs any module against any group. **This runs three, and none of them
changes anything**: because the catalogue is this console's safety boundary
and an ad hoc command is a hole in it. What is left after that hole is closed
is still the useful half: *can I reach these machines, and what are they*.

Anything that changes a host stays behind a declared target, where the danger
label, the confirmation and the lock all apply to it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .command import Command, ValidationError

# A group name as an inventory spells one, which is also all that may reach a
# command line from here.
_SAFE_GROUP = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:!&,*\[\]-]{0,127}$")


@dataclass(frozen=True)
class Question:
    """One thing that may be asked of a host, and what asking it means."""

    module: str
    label: str
    explanation: str


# Read-only, every one of them. `command` and `shell` are deliberately absent:
# they are how *anything at all* gets run, which is the boundary this keeps.
QUESTIONS = (
    Question("ping", "Can I reach these hosts?", "Answers, or says why it could not."),
    Question(
        "setup",
        "What are these hosts?",
        "Every fact Ansible can gather: the distribution, the interfaces, the memory.",
    ),
    Question(
        "gather_facts",
        "What are these hosts, briefly?",
        "The same, through the module a playbook uses at its start.",
    ),
)

MODULES = tuple(one.module for one in QUESTIONS)

# What asks the question, where a control plane does not wrap it in its own.
DEFAULT_COMMAND = ("ansible",)


def question(module: str) -> Question | None:
    return next((one for one in QUESTIONS if one.module == module), None)


def probe(*, inventory: str, group: str, module: str, ansible: list[str] | None = None) -> Command:
    """`ansible <group> -i <inventory> -m <module>`, and nothing else.

    The module is checked against the list rather than escaped, because a
    module name that needs escaping is one that should not be run.
    """
    if module not in MODULES:
        raise ValidationError(f"{module!r} is not a question this console asks")
    if not inventory:
        raise ValidationError("that environment has no inventory to ask")
    if not _SAFE_GROUP.match(group or ""):
        raise ValidationError("that is not a host group")
    argv = [*(ansible or DEFAULT_COMMAND), group, "-i", inventory, "-m", module]
    return Command.build(argv)
