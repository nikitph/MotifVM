from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MotifKey = Literal[
    "representation",
    "state",
    "storage",
    "addressing",
    "boundary",
    "invariant",
    "transition",
    "feedback",
    "search",
    "authority",
    "reconciliation",
    "scarcity",
    "composition",
    "hierarchy",
    "scheduling",
    "terminal_state",
]

MOTIF_KEYS: tuple[MotifKey, ...] = (
    "representation",
    "state",
    "storage",
    "addressing",
    "boundary",
    "invariant",
    "transition",
    "feedback",
    "search",
    "authority",
    "reconciliation",
    "scarcity",
    "composition",
    "hierarchy",
    "scheduling",
    "terminal_state",
)

PHASE_ORDER = {
    "normalize": 0,
    "analyze": 1,
    "plan": 2,
    "execute": 3,
    "verify": 4,
    "synthesize": 5,
}


def empty_motif_vector(value: float = 0.0) -> dict[str, float]:
    return {key: value for key in MOTIF_KEYS}


@dataclass
class StatePatch:
    nodes_to_add: list[dict[str, Any]] = field(default_factory=list)
    nodes_to_update: list[dict[str, Any]] = field(default_factory=list)
    edges_to_add: list[dict[str, Any]] = field(default_factory=list)
    artifacts_to_add: list[dict[str, Any]] = field(default_factory=list)
    decisions_to_add: list[dict[str, Any]] = field(default_factory=list)
    task_updates: dict[str, Any] = field(default_factory=dict)
    status_update: str | None = None
    motif_support_delta: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodesToAdd": self.nodes_to_add,
            "nodesToUpdate": self.nodes_to_update,
            "edgesToAdd": self.edges_to_add,
            "artifactsToAdd": self.artifacts_to_add,
            "decisionsToAdd": self.decisions_to_add,
            "taskUpdates": self.task_updates,
            "statusUpdate": self.status_update,
            "motifSupportDelta": self.motif_support_delta,
        }


@dataclass
class PassResult:
    status: Literal["success", "failed", "skipped"]
    patch: StatePatch = field(default_factory=StatePatch)
    invariant_results: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: int = 0
    tool_calls: int = 0
    error: str | None = None


@dataclass
class CompilerPass:
    name: str
    description: str
    phase: str
    strengthens: dict[str, float]
    requires: dict[str, float]
    depends_on: list[str]
    run: Any
    requires_node_types: list[str] = field(default_factory=list)
    requires_artifact_types: list[str] = field(default_factory=list)
    requires_resolved_inputs: bool = False
    produces_node_types: list[str] = field(default_factory=list)
    produces_artifact_types: list[str] = field(default_factory=list)
