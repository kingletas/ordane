"""What a control plane declares about Ansible itself, when it has no `ansible.cfg`.

Each declared setting becomes one `ANSIBLE_*` variable on the run's environment.
That composes: a repository's own `ansible.cfg` still supplies everything the
declaration does not name, and `ansible-config dump` reports each value's source,
so an override is visible in the run's own output rather than only here.

Pointing `ANSIBLE_CONFIG` at a file of our own is refused. It replaces the
repository's config outright instead of adding to it, so a plane whose config
sets `vault_password_file` would stop decrypting with nothing said.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field

from . import host

PREFIX = "ANSIBLE_"

# The whole-file switch. Named on its own because the reason it is refused is
# not the reason a credential is.
WHOLE_FILE = "ANSIBLE_CONFIG"

# A value that is itself a credential. Core Ansible has none, but collections
# add them, so the shape is refused rather than a list of names. `_FILE` and
# `_PATH` name where a secret lives, which is a path and is allowed.
SECRET_VALUE = re.compile(r"(?:PASSWORD|PASSPHRASE|SECRET|TOKEN)(?!_(?:FILE|PATH))(?:_|$)")

# Three of Ansible's four stdout callbacks print no `PLAY RECAP` at all, so a
# declared one can empty every host summary in the history without erroring.
RECAP_CALLBACK = "ANSIBLE_STDOUT_CALLBACK"
RECAP_KEEPING = ("default",)


class SettingsError(ValueError):
    """The `ansible:` block is present but unusable."""


@dataclass(frozen=True)
class Settings:
    """The `ANSIBLE_*` variables this control plane declares, in declared order."""

    values: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.values)

    @property
    def names(self) -> list[str]:
        return list(self.values)

    def applied_to(self, env: dict[str, str]) -> dict[str, str]:
        """A copy of `env` with every declared setting on it."""
        return {**env, **self.values}

    @property
    def display(self) -> str:
        """The assignments as they would be typed in front of a command."""
        return " ".join(f"{name}={value}" for name, value in self.values.items())

    @property
    def recap_at_risk(self) -> str:
        """The declared callback that would stop `PLAY RECAP` being printed."""
        chosen = self.values.get(RECAP_CALLBACK, "")
        return "" if chosen in RECAP_KEEPING else chosen


def read(raw: object) -> Settings:
    """Reads the `ansible:` block, refusing what must not be declared."""
    if raw is None:
        return Settings()
    if not isinstance(raw, dict):
        raise SettingsError(f"`ansible` must be a mapping, got {type(raw).__name__}")

    values: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip()
        _refuse(name)
        if value is None:
            raise SettingsError(f"`ansible.{name}` has no value")
        if isinstance(value, bool):
            # Ansible reads these as strings, and YAML's `false` is not `False`.
            values[name] = "True" if value else "False"
        elif isinstance(value, (str, int, float)):
            values[name] = str(value)
        else:
            raise SettingsError(
                f"`ansible.{name}` must be a string, number or boolean, got {type(value).__name__}"
            )
    return Settings(values=values)


def _refuse(name: str) -> None:
    if not name.startswith(PREFIX):
        raise SettingsError(
            f"`ansible.{name}` is not an Ansible setting: "
            f"every key here is an environment variable name, such as ANSIBLE_ROLES_PATH"
        )
    if name == WHOLE_FILE:
        raise SettingsError(
            f"`ansible.{WHOLE_FILE}` is refused: it replaces the repository's "
            "ansible.cfg rather than adding to it, so anything that file already "
            "sets: vault_password_file among them: would silently stop applying. "
            "Declare the individual settings instead."
        )
    if SECRET_VALUE.search(name):
        raise SettingsError(
            f"`ansible.{name}` takes a credential as its value, and this file is "
            "committed. Use the setting that names a file instead, or leave it to "
            "the environment the console is started from."
        )


# Ansible ignores an ANSIBLE_* variable it does not recognise, in silence. So a
# typo here is a setting that never applies while everything reports it did.
ASK_SECONDS = 20


def known_names() -> set[str] | None:
    """Every setting name Ansible knows, or None when it could not be asked.

    None is not an empty set: one means Ansible recognises nothing, the other
    means nobody looked, and a check that cannot tell them apart would report a
    typo in every name on a machine with no `ansible-config` on it.
    """
    found = host.which("ansible-config")
    if found is None:
        return None
    try:
        listed = subprocess.run(  # noqa: S603
            [found, "list", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=ASK_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if listed.returncode != 0 or not listed.stdout.strip():
        return None
    try:
        settings = json.loads(listed.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(settings, dict):
        return None

    names: set[str] = set()
    for spec in settings.values():
        if not isinstance(spec, dict):
            continue
        for entry in spec.get("env") or []:
            name = (entry or {}).get("name") if isinstance(entry, dict) else None
            if name:
                names.add(str(name))
    return names or None
