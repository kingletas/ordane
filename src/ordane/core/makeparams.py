"""The parameters a Makefile already documents, read out of the Makefile.

A control plane says what its recipes need — in the example line above a target,
and in the guard inside it. Reading that is what stops a console demanding a
config file before it can offer a form.

Only a name that appears in a documented `make <target> key=value` example is
treated as a parameter. A recipe reads plenty of other variables — `inventory`,
`owner`, `group` come from the profile — and offering those as fields would ask
somebody to fill in what the deployment already knows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# `# make apply-patch environment=production patch=M2PL-6611 state=present`
_EXAMPLE = re.compile(r"^\s*#+\s*make\s+(?P<target>[A-Za-z0-9][\w.-]*)\s+(?P<rest>.+)$")

# The `key=value` pairs in one of those, value quoted or bare.
_PAIR = re.compile(r"\b(?P<key>[a-z][a-z0-9_]*)=(?P<value>\"[^\"]*\"|'[^']*'|\S+)")

# `## admin-user-remove: delete Magento admin users (users="alice bob")`
_DOC = re.compile(r"^\s*##\s+(?P<target>[A-Za-z0-9][\w.-]*)\s*:\s*(?P<rest>.+)$")

# A help line that says so outright: `(requires release_name=)`.
_REQUIRES = re.compile(r"\brequires?\s+(?P<key>[a-z][a-z0-9_]*)=")

# A recipe that is one call to a script inside the repository. The guard that
# rejects a missing value often lives there rather than in the recipe.
_SCRIPT = re.compile(r"\$[{(](?:ROOT_DIR|CURDIR)[})]/(?P<path>[\w./-]+)")

# What a recipe writes when a value has to be supplied: `test -n "${users}"`,
# `test -z "${cmd}"`, or the shell's own `${cmd:?...}`.
_GUARD = re.compile(r"(?:test|\[)\s+-[nz]\s+[\"']?\$[{(](?P<key>[a-z][a-z0-9_]*)")
_SHELL_GUARD = re.compile(r"\$[{(](?P<key>[a-z][a-z0-9_]*):\?")

# `[ -z "${patch:-}" ]` and `[ "${state:-}" != "present" ]`. The `:-` form is
# written when a value may be unset, and testing it is deciding on it.
_TESTED = re.compile(r"\[[^\]]*\$\{(?P<key>[a-z][a-z0-9_]*):-\}[^\]]*\]")

# A target's own line: `deploy:` or `deploy: dependency`, never `VAR := value`.
_TARGET = re.compile(r"^(?P<name>[A-Za-z0-9][\w.-]*)\s*:(?!=)")

# Read but never offered: the deployment supplies these, not the person.
NEVER = frozenset({"environment", "cnf", "inventory"})


@dataclass(frozen=True)
class Found:
    """One parameter a Makefile documents for one target."""

    name: str
    example: str = ""
    required: bool = False


@dataclass
class _Target:
    params: dict[str, Found] = field(default_factory=dict)


def makefiles(repo: Path) -> list[Path]:
    """The Makefile and the fragments beside or one folder below it."""
    found = [repo / "Makefile"]
    found += sorted(repo.glob("*.mk"))
    found += sorted(repo.glob("*/*.mk"))
    return [p for p in found if p.is_file()]


def read(repo: Path, environment_var: str = "environment") -> dict[str, dict[str, Found]]:
    """Every target that documents a parameter, and what it documents."""
    found: dict[str, _Target] = {}
    for path in makefiles(repo):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        _scan(text, found, environment_var, repo)
    return {name: t.params for name, t in found.items() if t.params}


def _scan(text: str, found: dict[str, _Target], environment_var: str, repo: Path) -> None:
    skip = NEVER | {environment_var}
    documented: dict[str, dict[str, str]] = {}

    required: dict[str, set[str]] = {}
    # The `# make ...` example first: a help line saying `(requires x=)` names
    # the parameter without offering a value for it.
    for pattern in (_EXAMPLE, _DOC):
        for line in text.splitlines():
            match = pattern.match(line)
            if match is None:
                continue
            target = match.group("target")
            rest = match.group("rest")
            for named in _REQUIRES.finditer(rest):
                if named.group("key") not in skip:
                    required.setdefault(target, set()).add(named.group("key"))
                    documented.setdefault(target, {}).setdefault(named.group("key"), "")
            for pair in _PAIR.finditer(rest):
                key = pair.group("key")
                value = pair.group("value").strip("\"'").rstrip(")").strip()
                if key in skip or not value:
                    continue
                documented.setdefault(target, {})
                if not documented[target].get(key):
                    documented[target][key] = value

    for name, pairs in documented.items():
        entry = found.setdefault(name, _Target())
        for key, example in pairs.items():
            insisted = key in required.get(name, set())
            entry.params.setdefault(key, Found(name=key, example=example, required=insisted))

    for name, recipe in _recipes(text):
        entry = found.get(name)
        if entry is None:
            continue
        for guarded in _insisted_on(recipe, repo):
            if guarded in entry.params:
                entry.params[guarded] = Found(
                    name=guarded, example=entry.params[guarded].example, required=True
                )


def _insisted_on(recipe: str, repo: Path | None) -> set[str]:
    """The values this recipe refuses to run without, its own scripts included."""
    text = recipe
    for call in _SCRIPT.finditer(recipe):
        if repo is None:
            break
        script = repo / call.group("path")
        if script.is_file():
            try:
                text += "\n" + script.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    found = set()
    for pattern in (_GUARD, _SHELL_GUARD, _TESTED):
        found |= {m.group("key") for m in pattern.finditer(text)}
    return found


def _recipes(text: str) -> list[tuple[str, str]]:
    """Each target paired with the lines of its recipe."""
    found: list[tuple[str, str]] = []
    name = ""
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith(("\t", " ")) and name:
            body.append(line)
            continue
        if name:
            found.append((name, "\n".join(body)))
            name, body = "", []
        match = _TARGET.match(line)
        if match:
            name = match.group("name")
    if name:
        found.append((name, "\n".join(body)))
    return found
