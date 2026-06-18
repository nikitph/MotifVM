from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .passes import registry as executable_passes
from .storage import read_json


@dataclass
class PassSpec:
    name: str
    phase: str
    requiresNodeTypes: list[str]
    requiresArtifacts: list[str]
    producesNodeTypes: list[str]
    producesArtifacts: list[str]
    strengthens: dict[str, float]
    sideEffects: str


@dataclass
class InvariantSpec:
    id: str
    name: str
    domain: str
    severity: str
    requiresAuthority: bool


@dataclass
class ToolSpec:
    name: str
    capabilities: list[str]
    inputSchema: dict[str, Any]
    outputSchema: dict[str, Any]
    sideEffectClass: str
    approvalPolicy: str


def load_domain_profile(root: Path, domain: str | None) -> dict[str, Any] | None:
    if not domain:
        return None
    candidates = [
        root / "config" / "domains" / f"{domain}.json",
        root / ".motifvm" / "config" / "domains" / f"{domain}.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return read_json(candidate)
    builtins = {
        "dccb_audit": {
            "name": "dccb_audit",
            "description": "Built-in CRAR-focused DCCB audit profile.",
            "authorityRefs": [
                "domain_profile:dccb:crar_formula",
                "domain_profile:dccb:crar_threshold",
                "domain_profile:dccb:reported_crar_match",
            ],
            "invariants": [
                "DCCB_001_FORMULA",
                "DCCB_002_THRESHOLD",
                "DCCB_003_REPORTED_CRAR_MATCH",
                "DCCB_004_CAPITAL_COMPONENTS_PRESENT",
                "DCCB_005_NUMERIC_FIELDS_VALID",
                "DCCB_006_RWA_POSITIVE",
                "DCCB_007_THRESHOLD_CLASSIFICATION",
                "DCCB_008_REPORTED_STATUS_MATCH",
            ],
            "authorityRefsResolvedFrom": "builtin",
        },
        "code_review": {
            "name": "code_review",
            "description": "Built-in security-focused code review profile.",
            "authorityRefs": [
                "authority:code_review:security_policy",
                "authority:code_review:review_policy",
                "authority:code_review:test_policy",
            ],
            "invariants": [
                "CODE_001_CHANGED_FILES_HASHED",
                "CODE_002_DIFF_HAS_LINEAGE",
                "CODE_003_NO_UNCONDITIONAL_AUTH_ALLOW",
                "CODE_004_NO_SECRET_LITERAL",
                "CODE_005_TEST_STATUS_RECORDED",
                "CODE_006_FINAL_RISK_HAS_EVIDENCE",
                "CODE_007_REVIEW_TERMINAL_STATUS_VALID",
            ],
            "authorityRefsResolvedFrom": "builtin",
        },
    }
    if domain in builtins:
        return builtins[domain]
    raise FileNotFoundError(f"Domain profile not found: {domain}")


def pass_specs() -> list[PassSpec]:
    specs = []
    for item in executable_passes():
        specs.append(
            PassSpec(
                name=item.name,
                phase=item.phase,
                requiresNodeTypes=item.requires_node_types,
                requiresArtifacts=item.requires_artifact_types,
                producesNodeTypes=item.produces_node_types,
                producesArtifacts=item.produces_artifact_types,
                strengthens=item.strengthens,
                sideEffects="none",
            )
        )
    return specs


def invariant_specs() -> list[InvariantSpec]:
    universal = [
        "STRUCT_GOAL_001",
        "STRUCT_006",
        "TYPE_001",
        "COHER_002",
        "TRACE_001",
        "TRACE_002",
        "TRACE_003",
        "AUTH_001",
        "AUTH_002",
        "INPUT_001",
        "INPUT_002",
        "RECON_001",
        "RECON_002",
    ]
    dccb = [
        "DCCB_001_FORMULA",
        "DCCB_002_THRESHOLD",
        "DCCB_003_REPORTED_CRAR_MATCH",
        "DCCB_004_CAPITAL_COMPONENTS_PRESENT",
        "DCCB_005_NUMERIC_FIELDS_VALID",
        "DCCB_006_RWA_POSITIVE",
        "DCCB_007_THRESHOLD_CLASSIFICATION",
        "DCCB_008_REPORTED_STATUS_MATCH",
    ]
    code = [
        "CODE_001_CHANGED_FILES_HASHED",
        "CODE_002_DIFF_HAS_LINEAGE",
        "CODE_003_NO_UNCONDITIONAL_AUTH_ALLOW",
        "CODE_004_NO_SECRET_LITERAL",
        "CODE_005_TEST_STATUS_RECORDED",
        "CODE_006_FINAL_RISK_HAS_EVIDENCE",
        "CODE_007_REVIEW_TERMINAL_STATUS_VALID",
    ]
    specs: list[InvariantSpec] = []
    for invariant_id in universal:
        specs.append(InvariantSpec(invariant_id, invariant_id, "universal", "error", invariant_id.startswith("AUTH")))
    for invariant_id in dccb:
        specs.append(InvariantSpec(invariant_id, invariant_id, "dccb_audit", "error", True))
    for invariant_id in code:
        specs.append(InvariantSpec(invariant_id, invariant_id, "code_review", "error", True))
    return specs


def tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec("file_read", ["read_file", "read_diff", "read_csv"], {}, {}, "none", "auto"),
        ToolSpec("csv_read", ["read_csv"], {}, {}, "none", "auto"),
        ToolSpec("diff_scan", ["review_diff", "line_evidence"], {}, {}, "none", "auto"),
        ToolSpec("math_eval", ["compute_crar"], {}, {}, "none", "auto"),
    ]


def validate_pass_graph(domain_profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    passes = executable_passes()
    names = {item.name for item in passes}
    phases = {item.name: item.phase for item in passes}
    phase_order = {"normalize": 0, "analyze": 1, "plan": 2, "execute": 3, "verify": 4, "synthesize": 5}
    produced_nodes: set[str] = set()
    produced_artifacts: set[str] = {"pass_plan"}
    for item in passes:
        for dep in item.depends_on:
            if dep not in names:
                errors.append(_validation("PASSGRAPH_001", f"{item.name} depends on missing pass {dep}"))
            elif phase_order[phases[dep]] > phase_order[item.phase]:
                errors.append(_validation("PASSGRAPH_002", f"{item.name} depends on later phase pass {dep}"))
        missing_nodes = [required for required in item.requires_node_types if required not in produced_nodes]
        missing_artifacts = [
            required for required in item.requires_artifact_types if required not in produced_artifacts
        ]
        if item.name != "normalize_intent" and missing_nodes:
            errors.append(_validation("PASSGRAPH_003", f"{item.name} has impossible node requirements: {missing_nodes}"))
        if missing_artifacts:
            errors.append(_validation("PASSGRAPH_003", f"{item.name} has impossible artifact requirements: {missing_artifacts}"))
        produced_nodes.update(item.produces_node_types)
        produced_artifacts.update(item.produces_artifact_types)
        if not callable(item.run):
            errors.append(_validation("PASSGRAPH_004", f"{item.name} has no executable implementation"))
    if domain_profile:
        authority_refs = set(domain_profile.get("authorityRefs", []))
        invariant_ids = set(domain_profile.get("invariants", []))
        known = {item.id for item in invariant_specs()}
        missing_invariants = sorted(invariant_ids - known)
        if missing_invariants:
            errors.append(_validation("PASSGRAPH_004", f"Profile references unknown invariants: {missing_invariants}"))
        if invariant_ids and not authority_refs:
            errors.append(_validation("PASSGRAPH_005", "Profile has invariants but no authority refs"))
    return errors


def _validation(invariant_id: str, message: str) -> dict[str, Any]:
    return {
        "invariantId": invariant_id,
        "passed": False,
        "severity": "error",
        "message": message,
        "evidence": [],
        "autoFixable": False,
        "suggestedFix": None,
    }
