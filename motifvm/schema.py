from __future__ import annotations

from typing import Any

from .model import MOTIF_KEYS, StatePatch


def validate_state_patch(patch: StatePatch | dict[str, Any]) -> list[str]:
    data = patch.to_dict() if isinstance(patch, StatePatch) else patch
    errors = []
    list_fields = ["nodesToAdd", "nodesToUpdate", "edgesToAdd", "artifactsToAdd", "decisionsToAdd"]
    for field in list_fields:
        if not isinstance(data.get(field, []), list):
            errors.append(f"{field} must be a list")
    if not isinstance(data.get("taskUpdates", {}), dict):
        errors.append("taskUpdates must be an object")
    if not isinstance(data.get("motifSupportDelta", {}), dict):
        errors.append("motifSupportDelta must be an object")
    for key, value in data.get("motifSupportDelta", {}).items():
        if key not in MOTIF_KEYS:
            errors.append(f"Unknown motif key: {key}")
        if not isinstance(value, (int, float)) or value < 0:
            errors.append(f"Invalid motif delta for {key}")
    for node in data.get("nodesToAdd", []):
        if not isinstance(node, dict):
            errors.append(f"Node entry must be an object: {node!r}")
            continue
        for field in ("id", "type", "content", "status", "confidence", "source", "createdBy", "createdAt", "meta"):
            if field not in node:
                errors.append(f"Node missing {field}: {node.get('id', '<unknown>')}")
        if "confidence" in node and not 0 <= float(node["confidence"]) <= 1:
            errors.append(f"Node confidence out of range: {node.get('id')}")
    for edge in data.get("edgesToAdd", []):
        if not isinstance(edge, dict):
            errors.append(f"Edge entry must be an object: {edge!r}")
            continue
        for field in ("from", "to", "relation", "weight"):
            if field not in edge:
                errors.append(f"Edge missing {field}")
    return errors


def validate_evidence_ref(ref: dict[str, Any]) -> list[str]:
    errors = []
    for field in ("id", "inputId", "inputHash", "locatorType", "locator"):
        if not ref.get(field):
            errors.append(f"EvidenceRef missing {field}")
    if ref.get("locatorType") not in {"row", "line", "cell", "json_path", "byte_range"}:
        errors.append(f"Invalid EvidenceRef locatorType: {ref.get('locatorType')}")
    return errors


def validate_authority_ref(ref: dict[str, Any]) -> list[str]:
    errors = []
    for field in ("id", "sourceName", "sourceType", "confidence"):
        if field not in ref:
            errors.append(f"AuthorityRef missing {field}")
    if ref.get("sourceType") not in {"regulation", "domain_profile", "user", "input_file"}:
        errors.append(f"Invalid AuthorityRef sourceType: {ref.get('sourceType')}")
    if "confidence" in ref and not 0 <= float(ref["confidence"]) <= 1:
        errors.append(f"AuthorityRef confidence out of range: {ref.get('id')}")
    return errors


def validate_domain_profile(profile: dict[str, Any]) -> list[str]:
    errors = []
    for field in ("name", "description", "authorityRefs", "invariants"):
        if field not in profile:
            errors.append(f"DomainProfile missing {field}")
    if "authorityRefs" in profile and not isinstance(profile["authorityRefs"], list):
        errors.append("DomainProfile authorityRefs must be a list")
    if "invariants" in profile and not isinstance(profile["invariants"], list):
        errors.append("DomainProfile invariants must be a list")
    return errors


def validate_pass_spec(spec: Any) -> list[str]:
    errors = []
    for field in ("name", "phase", "requiresNodeTypes", "requiresArtifacts", "producesNodeTypes", "producesArtifacts", "strengthens"):
        if not hasattr(spec, field):
            errors.append(f"PassSpec missing {field}")
    if hasattr(spec, "phase") and spec.phase not in {"normalize", "analyze", "plan", "execute", "verify", "synthesize"}:
        errors.append(f"Invalid pass phase: {spec.phase}")
    return errors


def validate_cognitive_state(state: dict[str, Any]) -> list[str]:
    errors = []
    for field in ("id", "taskAst", "motifState", "graph", "artifacts", "invariants", "passHistory", "status"):
        if field not in state:
            errors.append(f"CognitiveState missing {field}")
    for ref in state.get("authorityRefs", []):
        errors.extend(validate_authority_ref(ref))
    for node in state.get("graph", {}).get("nodes", {}).values():
        evidence_ref = node.get("meta", {}).get("evidenceRef")
        if evidence_ref:
            errors.extend(validate_evidence_ref(evidence_ref))
    return errors
