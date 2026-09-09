"""The seven steps, in the order that makes each one possible.

This replaces five scattered `Setup needed` states with one sequence. Each step
turns a specific thing on, and says which, so a person can stop after any of
them and still have a console that works.

Nothing here is a fault. A repository that has not finished setting up is
`waiting`, which is blue: amber and red are kept for things that actually went
wrong, and spending them here is what made a first launch look like an outage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..core.catalog import Catalog
from ..core.config import CONFIG_NAME, Config
from ..presentation.text import plural
from ..record.store import Run
from .metrics import Snapshot

# What a step's button asks the window to do. Named rather than wired: this
# layer knows no front end, and a front end that has no such button simply
# draws none.
OPEN_CONFIG = "open-config"
CHOOSE_ENVIRONMENTS = "choose-environments"
OPEN_ACTIONS = "open-actions"
OPEN_ENVIRONMENTS = "open-environments"
OPEN_DELIVERY = "open-delivery"
EDIT_OBJECTIVES = "edit-objectives"
CHECK = "check"

BUTTONS = {
    OPEN_CONFIG: f"Open {CONFIG_NAME}",
    CHOOSE_ENVIRONMENTS: "Manage environments",
    OPEN_ACTIONS: "Open Actions",
    OPEN_ENVIRONMENTS: "Open Environments",
    OPEN_DELIVERY: "Open Delivery",
    EDIT_OBJECTIVES: "Set up objectives",
    CHECK: "Check the repository",
}


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    note: str
    unlocks: str = ""
    done: bool = False
    remedy: str = ""

    @property
    def button(self) -> str:
        return BUTTONS.get(self.remedy, "")


@dataclass(frozen=True)
class Setup:
    steps: list[Step] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.steps)

    @property
    def done(self) -> int:
        return sum(1 for step in self.steps if step.done)

    @property
    def complete(self) -> bool:
        return self.done == self.total and self.total > 0

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 1.0

    @property
    def left(self) -> int:
        return self.total - self.done

    @property
    def next_step(self) -> Step | None:
        """The first one not done, which is the only one worth naming."""
        return next((step for step in self.steps if not step.done), None)

    @property
    def progress_text(self) -> str:
        return f"{self.done} of {self.total} done"

    def headline(self, snapshot: Snapshot) -> str:
        """What the setup card leads with: what Ordane can measure, not what is missing."""
        measurable = len(snapshot.measures)
        measured = sum(1 for measure in snapshot.measures if measure.has_data)
        if measured == measurable:
            return "Ordane is measuring every delivery signal"
        return f"Ordane can measure {measured} of the {measurable} delivery signals"

    @property
    def sentence(self) -> str:
        """One line naming the next step and what it turns on."""
        step = self.next_step
        if step is None:
            return "Everything Ordane can be told about this repository, it has been told."
        left = plural(self.left, "step")
        return f"{left} left, and each one turns something on. Next up: {_lower(step.title)}."


def assess(
    *,
    catalog: Catalog | None,
    config: Config,
    snapshot: Snapshot,
    runs: list[Run],
    repo: Path,
    history_path: Path,
) -> Setup:
    """The seven steps against this repository, in order."""
    readable = catalog is not None
    environments = list(catalog.environments) if catalog else []
    unusable = [one for one in environments if not one.usable]
    allowed = list(config.allow_environments)
    deployed = [run for run in runs if run.labels.get("deploy") == "true"]
    released = _has_rows(history_path)
    measured_slos = [slo for slo in snapshot.slos if slo.has_data]

    return Setup(
        steps=[
            Step(
                key="repository",
                title="Point Ordane at a repository",
                note=(
                    f"{repo.name}, read as a control plane"
                    if readable
                    else "The repository cannot be read, so there is nothing to offer yet."
                ),
                unlocks="Everything else",
                done=readable,
                remedy="" if readable else CHECK,
            ),
            Step(
                key="config",
                title=f"Write {CONFIG_NAME}",
                note=(
                    f"{plural(len(catalog.targets) if catalog else 0, 'action')}, "
                    f"{plural(len(environments), 'environment')}, "
                    f"{plural(len(config.slos), 'objective')}"
                    if (repo / CONFIG_NAME).is_file()
                    else f"`ordane init` writes a starting {CONFIG_NAME} describing what "
                    "it actually found."
                ),
                unlocks="Groups, danger levels, runbooks and objectives",
                done=(repo / CONFIG_NAME).is_file(),
                remedy=OPEN_CONFIG,
            ),
            Step(
                key="allow",
                title="Say which environments this console may reach",
                note=(
                    f"{', '.join(allowed)} may be launched against"
                    if allowed
                    else "Nothing is chosen for you, because that is a decision about "
                    "production. Until one is named, this repository is read-only."
                ),
                unlocks="Launching anything at all",
                done=bool(allowed),
                remedy=CHOOSE_ENVIRONMENTS,
            ),
            Step(
                key="reach",
                title="Give every declared environment a host source",
                note=(
                    f"{plural(len(environments), 'environment')}, all with an inventory"
                    if readable and not unusable
                    else ", ".join(f"{one.name}: {one.reason}" for one in unusable)
                    or "Nothing has been read yet."
                ),
                unlocks="The environments that cannot be targeted yet",
                done=readable and not unusable and bool(environments),
                remedy=OPEN_ENVIRONMENTS,
            ),
            Step(
                key="deploy",
                title="Launch one deploy from Ordane",
                note=(
                    f"{plural(len(deployed), 'deploy')} recorded"
                    if deployed
                    else "Ordane only counts what it launched. Run a deploy once and the "
                    "count begins."
                ),
                unlocks="Change failure rate and time to restore",
                done=bool(deployed),
                remedy=OPEN_ACTIONS,
            ),
            Step(
                key="history",
                title="Give the release history a source",
                note=(
                    f"{history_path.name} has releases in it"
                    if released
                    else f"{history_path.name} is where release frequency and lead time "
                    "are read from. The reporter writes it; `make dora` in the control "
                    "plane."
                ),
                unlocks="Release frequency and lead time for changes",
                done=released,
                remedy=OPEN_DELIVERY,
            ),
            Step(
                key="objectives",
                title="Set a target this estate holds itself to",
                note=(
                    f"{len(measured_slos)} of {plural(len(snapshot.slos), 'objective')} measured"
                    if config.slos
                    else "An objective is a target with a window and a source. Without "
                    "one there is nothing to be under or over."
                ),
                unlocks="The service objectives",
                done=bool(measured_slos),
                remedy=EDIT_OBJECTIVES,
            ),
        ]
    )


def _has_rows(path: Path) -> bool:
    """Whether the release history holds anything, without parsing it twice."""
    try:
        with path.open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip()) > 1
    except OSError:
        return False


def _lower(title: str) -> str:
    """A step's title inside a sentence, which is not where a capital belongs."""
    return title[:1].lower() + title[1:] if title else title
