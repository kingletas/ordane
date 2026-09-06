"""Masks secrets before run output reaches disk.

The pattern set covers the shapes a secret takes in output. This is a second
line of defence: the first is `no_log:` on the tasks that handle secrets.
"""

from __future__ import annotations

import re

from ..presentation.language import MASK

_WORDS = r"api_?key|secret|token|passwd|password|auth|credential|private_?key"
_NAME = rf"[A-Za-z0-9_.\-]*(?:{_WORDS})[A-Za-z0-9_.\-]*"

# Each pattern keeps group 1 and replaces group 2, so the name stays readable.
_ASSIGNMENTS: list[re.Pattern[str]] = [
    # KEY=value and export KEY=value, as the profile files write them.
    re.compile(rf"(?im)^(\s*(?:export\s+)?{_NAME}\s*=\s*)(\S+)$"),
    # key: value and key = value, quoted or bare, anywhere in a line.
    re.compile(rf"""(?i)\b({_NAME}\s*[:=]\s*)(["'][^"'\n]{{4,}}["']|[^\s,;)"'\n]{{4,}})"""),
    # Ansible's own no_log placeholder is already safe; a --extra-var is not.
    re.compile(rf"""(?i)(--extra-vars?[= ]\s*["']?[^"'\n]*?{_NAME}=)(\S+)"""),
]

_STANDALONE: list[re.Pattern[str]] = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"\bxox[abprs]-[0-9A-Za-z\-]{10,}"),
    re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{16,}"),
    re.compile(r"\bSG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"),
    re.compile(
        r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----[\s\S]*?"
        r"-----END (?:[A-Z ]+ )?PRIVATE KEY-----"
    ),
    re.compile(r"\b[a-z][a-z0-9+.\-]*://[^:\s/]+:[^@\s]{4,}@"),
]

# A value that is obviously not a secret, so a masked log stays readable.
_PLACEHOLDER = re.compile(
    r"^(?:''|\"\"|''''|none|null|nil|true|false|yes|no|0|1|latest|changeme|"
    r"xxx+|\.{3,}|<[^>]*>|\$\{[^}]*\}|\{\{[^}]*\}\})$",
    re.IGNORECASE,
)


class Redactor:
    """Masks secret-shaped text, plus any literal values it is told about."""

    def __init__(self, literals: list[str] | None = None) -> None:
        self._literals = sorted(
            {v for v in (literals or []) if v and len(v) >= 4 and not _PLACEHOLDER.match(v)},
            key=len,
            reverse=True,
        )

    def also(self, value: str) -> None:
        """Masks one more literal from here on.

        A vault password is typed after the run has started, so the redactor
        has to learn it mid-flight or it reaches the log the moment Ansible
        echoes anything containing it.
        """
        if not value or len(value) < 4 or _PLACEHOLDER.match(value):
            return
        self._literals = sorted({*self._literals, value}, key=len, reverse=True)

    def line(self, text: str) -> str:
        """Returns the line with every recognised secret replaced."""
        for literal in self._literals:
            text = text.replace(literal, MASK)
        for pattern in _STANDALONE:
            text = pattern.sub(MASK, text)
        for pattern in _ASSIGNMENTS:
            text = pattern.sub(_mask_second_group, text)
        return text


def _mask_second_group(match: re.Match[str]) -> str:
    value = match.group(2)
    if _PLACEHOLDER.match(value.strip("\"'")):
        return match.group(0)
    return f"{match.group(1)}{MASK}"
