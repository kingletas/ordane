"""How exposed a run is, read from the name of the environment it runs against.

Nothing a control plane does is dangerous in itself: `ping` against docker is a
keystroke, and the same `ping` against production is a keystroke against the
thing customers are using. So the environment decides, and a target's own rating
can only raise what the environment already says.

The safe list is deliberately short. A name nobody recognises is not safe, it is
unknown, and unknown is said out loud rather than assumed either way.
"""

from __future__ import annotations

PRODUCTION = "production"
SAFE = "safe"
UNKNOWN = "unknown"

# Checked first, and a name carrying any of these is production even when it
# also carries a safe word: `dev-mirror-of-prod` reaches production hosts.
LIVE_WORDS = ("production", "prod", "prd", "live")

# Only the four families that were named, and the spellings each one has.
# Anything else is unknown on purpose — widening this list is how a real
# environment quietly becomes a safe one.
SAFE_WORDS = (
    "staging",
    "stage",
    "stg",
    "development",
    "develop",
    "dev",
    "docker",
    "localhost",
    "local",
)


def reading(name: str) -> str:
    """Whether this environment is production, one of the safe kinds, or unknown."""
    said = (name or "").casefold()
    if not said:
        return UNKNOWN
    if any(word in said for word in LIVE_WORDS):
        return PRODUCTION
    if any(word in said for word in SAFE_WORDS):
        return SAFE
    return UNKNOWN


def floor(name: str) -> str:
    """The least a run against this environment may be presented as."""
    return {PRODUCTION: "high", SAFE: "low"}.get(reading(name), "medium")


def caution(name: str) -> str:
    """The sentence that goes above the button, or empty where there is none."""
    said = reading(name)
    if said == PRODUCTION:
        return f"Customers are on {name}. Whatever this does, it does to them."
    if said == UNKNOWN:
        return f"This could be dangerous: nothing in the name “{name}” says what it is."
    return ""


# Worst first, so a target's own rating can raise what the environment says and
# never lower it.
_RANK = ("low", "medium", "high")


def worst(*levels: str) -> str:
    """The most severe of the levels given."""
    return max((one for one in levels if one in _RANK), key=_RANK.index, default="low")


def level_for(name: str, declared: str = "low") -> str:
    """How a run should be presented: the environment's floor, or worse."""
    return worst(floor(name), declared)


def clause(name: str) -> str:
    """The same warning as a clause, for a sentence that already names the place."""
    said = reading(name)
    if said == PRODUCTION:
        return "customers are on it"
    if said == UNKNOWN:
        return "nothing in the name says whether that is production"
    return ""


def label(name: str) -> str:
    """A word for a chip beside the environment, or empty where none is needed."""
    said = reading(name)
    if said == PRODUCTION:
        return "Production"
    if said == UNKNOWN:
        return "Could be dangerous"
    return ""
