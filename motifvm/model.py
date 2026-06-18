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
class EvidenceRef:
    id: str
    input_id: str
    input_hash: str
    locator_type: str
    locator: str
    excerpt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "inputId": self.input_id,
            "inputHash": self.input_hash,
            "locatorType": self.locator_type,
            "locator": self.locator,
            "excerpt": self.excerpt,
            "metadata": self.metadata,
        }


@dataclass
class ExtractedFact:
    id: str
    kind: str
    value: Any
    evidence_ref_id: str
    confidence: float
    extracted_by: str
    domain_hints: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "value": self.value,
            "evidenceRefId": self.evidence_ref_id,
            "confidence": self.confidence,
            "extractedBy": self.extracted_by,
            "domainHints": self.domain_hints,
            "metadata": self.metadata,
        }


@dataclass
class AdapterResult:
    adapter_id: str
    adapter_version: str
    input_id: str
    path: str
    content_hash: str
    resolved_artifacts: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    extracted_facts: list[ExtractedFact] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_artifact(self) -> dict[str, Any]:
        return {
            "id": f"artifact:adapter:{self.input_id}",
            "type": "adapter_output",
            "content": {
                "adapterId": self.adapter_id,
                "adapterVersion": self.adapter_version,
                "inputId": self.input_id,
                "path": self.path,
                "contentHash": self.content_hash,
                "evidenceRefs": [item.to_dict() for item in self.evidence_refs],
                "extractedFacts": [item.to_dict() for item in self.extracted_facts],
                "metadata": self.metadata,
            },
            "producedBy": self.adapter_id,
        }


@dataclass
class ArtifactAdapter:
    adapter_id: str
    version: str
    media_types: list[str]
    run: Any

    def adapt(self, input_ref: dict[str, Any], path: Any) -> AdapterResult:
        return self.run(input_ref, path)


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
