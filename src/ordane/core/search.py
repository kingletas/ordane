"""Ranks targets against what was typed, by the kind of match rather than a score.

A run of the right letters in the wrong word is a different kind of match from
the word itself, and no weighting reconciles the two: `dep` should find `deploy`
before it finds `admin-user-remove`, which contains d, e and p in order. So a
match is classed first and only ordered within its class.
"""

from __future__ import annotations

from dataclasses import dataclass

# Worst to best is bottom to top: the list is read in this order.
EXACT = 0
PREFIX = 1
WORD = 2
INSIDE = 3
DESCRIPTION = 4
LETTERS = 5

CLASS_NAMES = {
    EXACT: "the target itself",
    PREFIX: "starts with it",
    WORD: "a word in the name",
    INSIDE: "inside the name",
    DESCRIPTION: "in the description",
    LETTERS: "those letters, in order",
}


@dataclass(frozen=True)
class Match:
    target: object
    kind: int

    @property
    def reason(self) -> str:
        return CLASS_NAMES[self.kind]


def classify(name: str, description: str, needle: str) -> int | None:
    """Which class this target falls into for this needle, or None for no match."""
    name = name.lower()
    description = description.lower()
    if name == needle:
        return EXACT
    if name.startswith(needle):
        return PREFIX
    if needle in _words(name):
        return WORD
    if needle in name:
        return INSIDE
    if needle in description:
        return DESCRIPTION
    if _in_order(name, needle):
        return LETTERS
    return None


def _words(name: str) -> list[str]:
    """A make target is written in kebab or snake case, and each part is a word."""
    return name.replace("_", "-").replace(".", "-").split("-")


def _in_order(haystack: str, needle: str) -> bool:
    position = 0
    for character in needle:
        position = haystack.find(character, position)
        if position < 0:
            return False
        position += 1
    return True


def rank(targets, needle: str) -> list[Match]:
    """Every target that matches, best class first, declared order within a class."""
    needle = needle.strip().lower()
    if not needle:
        return [Match(target=t, kind=EXACT) for t in targets]
    matches = []
    for index, target in enumerate(targets):
        kind = classify(target.name, target.description, needle)
        if kind is not None:
            matches.append((kind, index, target))
    matches.sort(key=lambda item: (item[0], item[1]))
    return [Match(target=target, kind=kind) for kind, _, target in matches]
