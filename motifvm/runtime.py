from __future__ import annotations

import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .authority import authority_ref
from .compiler import compile_reasoning_plan, create_motif_frame, load_pass_effects, replan_after_failure
from .invariants import run_invariants
from .failure import classify_failure
from .llm import DeepSeekLLMClient, MockLLMClient, StructuredCallSpec
from .model import MOTIF_KEYS, CompilerPass, PassResult, StatePatch, empty_motif_vector
from .passes import edge, node, registry
from .patch_auth import authorize_patch
from .registry import load_domain_profile, validate_pass_graph
from .schema import validate_cognitive_state, validate_state_patch
from .storage import append_jsonl, commit_state, ensure_store, read_json, utc_now, write_json


def parse_request(request: str, domain: str | None = None) -> dict[str, Any]:
    lower = request.lower()
    intent = "verify" if any(word in lower for word in ("verify", "check", "audit")) else "analyze"
    detected_domain = domain
    if detected_domain is None and any(word in lower for word in ("dccb", "crar", "rbi", "nabard")):
        detected_domain = "dccb_audit"
    if detected_domain is None and any(word in lower for word in ("code", "diff", "review", "security")):
        detected_domain = "code_review"
    inputs = []
    seen = set()
    for token in re.findall(r"(?<!\w)([./~\w-]+\.(?:csv|json|txt|xlsx|patch))(?!\w)", request):
        if token not in seen:
            seen.add(token)
            inputs.append(
                {
                    "id": f"input:{len(inputs) + 1}",
                    "label": Path(token).name,
                    "type": "data",
                    "location": token,
                    "resolved": False,
                }
            )
    if detected_domain == "dccb_audit" and "crar" in lower:
        outputs = [
            {"id": "output:crar", "description": "CRAR percentage", "format": "number", "required": True},
            {
                "id": "output:breakdown",
                "description": "Component breakdown",
                "format": "table",
                "required": True,
            },
            {
                "id": "output:compliance",
                "description": "Compliant or non-compliant flag",
                "format": "boolean",
                "required": True,
            },
        ]
    elif detected_domain == "code_review":
        outputs = [
            {"id": "output:risk", "description": "Review risk classification", "format": "text", "required": True},
            {"id": "output:findings", "description": "Review findings", "format": "table", "required": True},
        ]
    else:
        outputs = [
            {
                "id": "output:summary",
                "description": "Final answer",
                "format": "text",
                "required": True,
            }
        ]
    return {
        "id": f"task:{uuid.uuid4().hex[:10]}",
        "goal": request,
        "intent": intent,
        "inputs": inputs,
        "constraints": [],
        "preferences": [],
        "subtasks": [],
        "requiredOutputs": outputs,
        "uncertainty": [],
        "meta": {"rawRequest": request, "timestamp": utc_now(), "domain": detected_domain},
    }


def diagnose(task_ast: dict[str, Any]) -> dict[str, float]:
    signature = empty_motif_vector(0.2)
    goal = task_ast.get("goal", "").lower()
    domain = task_ast.get("meta", {}).get("domain")
    if task_ast.get("inputs"):
        signature.update({"addressing": 0.8, "storage": 0.65, "state": 0.65})
    if task_ast.get("intent") in ("verify", "review", "debug"):
        signature.update({"invariant": 0.9, "feedback": 0.75, "terminal_state": 0.75})
    if domain == "dccb_audit" or "crar" in goal:
        signature.update(
            {
                "representation": 0.6,
                "state": 0.8,
                "storage": 0.7,
                "addressing": 0.9,
                "boundary": 0.55,
                "invariant": 1.0,
                "transition": 0.5,
                "feedback": 0.75,
                "search": 0.25,
                "authority": 0.85,
                "reconciliation": 0.55,
                "scarcity": 0.25,
                "composition": 0.7,
                "hierarchy": 0.5,
                "scheduling": 0.35,
                "terminal_state": 0.85,
            }
        )
    elif domain == "code_review":
        signature.update(
            {
                "representation": 0.65,
                "state": 0.65,
                "storage": 0.6,
                "addressing": 0.9,
                "boundary": 0.7,
                "invariant": 0.9,
                "transition": 0.45,
                "feedback": 0.75,
                "search": 0.25,
                "authority": 0.75,
                "reconciliation": 0.35,
                "scarcity": 0.25,
                "composition": 0.55,
                "hierarchy": 0.35,
                "scheduling": 0.25,
                "terminal_state": 0.85,
            }
        )
    elif any(word in goal for word in ("build", "create", "generate")):
        signature.update(
            {"representation": 0.75, "composition": 0.65, "transition": 0.65, "terminal_state": 0.7}
        )
    return signature


def initial_state(task_ast: dict[str, Any], required: dict[str, float]) -> dict[str, Any]:
    supported = empty_motif_vector(0.0)
    authorities = []
    if task_ast.get("meta", {}).get("domain") == "dccb_audit":
        authorities = [
            authority_ref(
                "domain_profile:dccb:crar_formula",
                "DCCB audit domain profile - CRAR formula",
                "domain_profile",
                "0.4.5",
                "authority_sources/dccb/crar_rules.md#crar-formula",
                "crar-formula",
                "CRAR = (Tier I Capital + Tier II Capital) / Risk Weighted Assets * 100.",
            ),
            authority_ref(
                "domain_profile:dccb:crar_threshold",
                "DCCB audit domain profile - CRAR threshold",
                "domain_profile",
                "0.4.5",
                "authority_sources/dccb/crar_rules.md#threshold",
                "threshold",
                "The demo profile uses 9.00 percent as the CRAR threshold.",
            ),
            authority_ref(
                "domain_profile:dccb:reported_crar_match",
                "DCCB audit domain profile - reported CRAR consistency",
                "domain_profile",
                "0.4.5",
                "authority_sources/dccb/crar_rules.md#reported-value-consistency",
                "reported-value-consistency",
                "If a reported CRAR value is present, it must match the recomputed CRAR within the runtime tolerance.",
            ),
        ]
    elif task_ast.get("meta", {}).get("domain") == "code_review":
        authorities = [
            authority_ref(
                "authority:code_review:security_policy",
                "Code review security policy",
                "domain_profile",
                "0.4.5",
                "authority_sources/code_review/security_policy.md#security-risks",
                "security-risks",
                "The review profile flags high-confidence security risks in added diff lines:",
            ),
            authority_ref(
                "authority:code_review:review_policy",
                "Code review policy",
                "domain_profile",
                "0.4.5",
                "authority_sources/code_review/security_policy.md#review-lineage",
                "review-lineage",
                "Every review finding must trace to an input file hash and line-level evidence.",
            ),
            authority_ref(
                "authority:code_review:test_policy",
                "Code review test policy",
                "domain_profile",
                "0.4.5",
                "authority_sources/code_review/security_policy.md#test-recording",
                "test-recording",
                "The review artifact must record whether test evidence was available.",
                confidence=0.7,
            ),
        ]
    return {
        "id": f"state:{uuid.uuid4().hex[:10]}",
        "taskAst": task_ast,
        "authorityRefs": authorities,
        "inputManifest": [],
        "motifState": {
            "required": required,
            "supported": supported,
            "gap": compute_gap(required, supported),
        },
        "motifSignature": required,
        "motifFrame": create_motif_frame(task_ast, required, supported),
        "reasoningPlan": {},
        "reasoningPlans": [],
        "verificationPolicy": {},
        "replanEvents": [],
        "graph": {"nodes": {}, "edges": []},
        "artifacts": [],
        "decisions": [],
        "invariants": [],
        "passHistory": [],
        "patchTimeline": [],
        "executionLog": [],
        "branch": "main",
        "parentCommit": None,
        "status": "planning",
    }


def compute_gap(required: dict[str, float], supported: dict[str, float]) -> dict[str, float]:
    return {key: max(0.0, round(required.get(key, 0.0) - supported.get(key, 0.0), 4)) for key in MOTIF_KEYS}


def select_passes(
    passes: list[CompilerPass],
    required: dict[str, float],
    supported: dict[str, float],
    threshold: float = 0.15,
) -> list[CompilerPass]:
    task_ast = {
        "id": "task:legacy_planner",
        "goal": "legacy motif-gap planning helper",
        "intent": "verify",
        "inputs": [{"id": "input:legacy", "location": "legacy.csv"}] if required.get("addressing", 0.0) >= threshold else [],
        "meta": {"domain": "dccb_audit"} if required.get("authority", 0.0) >= 0.75 else {},
    }
    frame = create_motif_frame(task_ast, required, supported)
    pass_effects = {item.name: {"strengthens": {key: 0.3 for key in item.strengthens}, "cost": {}} for item in passes}
    plan = compile_reasoning_plan(task_ast, frame, passes, pass_effects)
    by_name = {item.name: item for item in passes}
    return [by_name[name] for name in plan["selectedPasses"] if name in by_name]


def validate_patch(state: dict[str, Any], patch: StatePatch) -> list[str]:
    errors: list[str] = validate_state_patch(patch)
    existing = set(state.get("graph", {}).get("nodes", {}))
    incoming = {node["id"] for node in patch.nodes_to_add}
    duplicates = existing & incoming
    if duplicates:
        errors.append(f"Patch adds duplicate nodes: {', '.join(sorted(duplicates))}")
    known_after = existing | incoming
    for candidate in patch.edges_to_add:
        if candidate.get("from") not in known_after:
            errors.append(f"Patch edge source does not exist: {candidate.get('from')}")
        if candidate.get("to") not in known_after:
            errors.append(f"Patch edge target does not exist: {candidate.get('to')}")
    for key, value in patch.motif_support_delta.items():
        if key not in MOTIF_KEYS:
            errors.append(f"Patch updates unknown motif key: {key}")
        if value < 0:
            errors.append(f"Patch has negative support delta for {key}")
    return errors


def validate_llm_patch(state: dict[str, Any], patch: StatePatch) -> list[str]:
    errors = validate_patch(state, patch)
    errors.extend(authorize_patch(patch, "llm", state.get("taskAst", {}).get("meta", {}).get("domain")))
    return errors


def emit_llm_narrative(state: dict[str, Any], llm_provider: str | None) -> dict[str, Any]:
    if llm_provider not in {"mock", "deepseek"}:
        return state
    final_text = next(
        (
            artifact.get("content", {}).get("text")
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "final_output"
        ),
        "",
    )
    client = MockLLMClient() if llm_provider == "mock" else DeepSeekLLMClient()
    narrative, record = client.call_structured(
        StructuredCallSpec(
            "CALL_EMIT",
            {},
            {"type": "object", "required": ["text"]},
            0.2,
            1,
            fallback=lambda payload: {"text": payload["fallbackText"]},
        ),
        {
            "status": state.get("status"),
            "terminalReason": state.get("terminalReason"),
            "failureClass": state.get("failureClass"),
            "fallbackText": final_text,
            "deterministicReport": final_text,
        },
    )
    state.setdefault("llmCalls", []).append(record)
    patch = StatePatch(
        artifacts_to_add=[
            {
                "id": "artifact:llm:narrative",
                "type": "llm_narrative",
                "content": {
                    "text": narrative.get("text", final_text),
                    "comparedAgainst": "artifact:final_output",
                    "mayAlterTerminalStatus": False,
                    "mayAlterInvariants": False,
                    "mayAlterInputManifest": False,
                    "mayAlterAuthorityRefs": False,
                },
                "producedBy": "CALL_EMIT",
                "timestamp": utc_now(),
            }
        ]
    )
    errors = validate_llm_patch(state, patch)
    if errors:
        state.setdefault("patchTimeline", []).append(
            _patch_timeline_record("CALL_EMIT", "llm", patch, False, errors, len(state.get("invariants", [])), len(state.get("invariants", [])))
        )
        state.setdefault("executionLog", []).append(
            {
                "timestamp": utc_now(),
                "phase": "synthesize",
                "event": "llm_patch_rejected",
                "details": {"failureClass": "llm_patch_rejected", "errors": errors},
            }
        )
        return state
    next_state = apply_patch(state, patch)
    next_state.setdefault("patchTimeline", []).append(
        _patch_timeline_record("CALL_EMIT", "llm", patch, True, [], len(state.get("invariants", [])), len(state.get("invariants", [])))
    )
    return next_state


def check_pass_preconditions(state: dict[str, Any], compiler_pass: CompilerPass) -> list[str]:
    errors: list[str] = []
    node_types = {
        node.get("type") for node in state.get("graph", {}).get("nodes", {}).values()
    }
    artifact_types = {artifact.get("type") for artifact in state.get("artifacts", [])}
    for required_type in compiler_pass.requires_node_types:
        if required_type not in node_types:
            errors.append(f"Missing required node type: {required_type}")
    for required_type in compiler_pass.requires_artifact_types:
        if required_type not in artifact_types:
            errors.append(f"Missing required artifact type: {required_type}")
    if compiler_pass.requires_resolved_inputs and not any(
        item.get("resolved") for item in state.get("taskAst", {}).get("inputs", [])
    ):
        errors.append("Missing resolved input reference")
    return errors


def apply_patch(state: dict[str, Any], patch: StatePatch) -> dict[str, Any]:
    next_state = deepcopy(state)
    nodes = next_state["graph"]["nodes"]
    for item in patch.nodes_to_add:
        nodes[item["id"]] = item
    for update in patch.nodes_to_update:
        node_id = update["id"]
        if node_id in nodes:
            nodes[node_id].update(update.get("changes", {}))
    next_state["graph"]["edges"].extend(patch.edges_to_add)
    next_state["artifacts"].extend(patch.artifacts_to_add)
    _refresh_input_manifest(next_state)
    next_state["decisions"].extend(patch.decisions_to_add)
    next_state["taskAst"].update(patch.task_updates)
    if patch.status_update:
        next_state["status"] = patch.status_update
    supported = next_state["motifState"]["supported"]
    for key, delta in patch.motif_support_delta.items():
        supported[key] = min(1.0, round(supported.get(key, 0.0) + delta, 4))
    next_state["motifState"]["gap"] = compute_gap(next_state["motifState"]["required"], supported)
    return next_state


def _patch_timeline_record(
    pass_name: str,
    role: str,
    patch: StatePatch,
    authorized: bool,
    errors: list[str] | None,
    before_invariants: int,
    after_invariants: int,
) -> dict[str, Any]:
    return {
        "passName": pass_name,
        "role": role,
        "authorized": authorized,
        "authorizationErrors": errors or [],
        "nodesAdded": [item.get("id") for item in patch.nodes_to_add],
        "nodesUpdated": [item.get("id") for item in patch.nodes_to_update],
        "edgesAdded": [
            {"from": item.get("from"), "to": item.get("to"), "relation": item.get("relation")}
            for item in patch.edges_to_add
        ],
        "artifactsAdded": [item.get("id") for item in patch.artifacts_to_add],
        "decisionsAdded": [item.get("id") for item in patch.decisions_to_add],
        "motifSupportDelta": patch.motif_support_delta,
        "invariantsBefore": before_invariants,
        "invariantsAfter": after_invariants,
        "timestamp": utc_now(),
    }


def _refresh_input_manifest(state: dict[str, Any]) -> None:
    manifest = []
    for artifact in state.get("artifacts", []):
        if artifact.get("type") != "resolved_input":
            continue
        content = artifact.get("content", {})
        manifest.append(
            {
                "inputId": content.get("inputId"),
                "path": content.get("path"),
                "sha256": content.get("sha256"),
                "rowsRead": content.get("rowsRead"),
                "readAt": content.get("readAt"),
                "artifactId": artifact.get("id"),
            }
        )
    state["inputManifest"] = manifest


def apply_reconciliation(state: dict[str, Any], failures: list[dict[str, Any]]) -> dict[str, Any]:
    failed_ids = {item.get("invariantId") for item in failures}
    if "DCCB_003_REPORTED_CRAR_MATCH" not in failed_ids:
        return state
    crar = next(
        (
            artifact
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "dccb_crar_computation"
        ),
        None,
    )
    if not crar:
        return state
    content = crar.get("content", {})
    computed = float(content.get("computedCrar", 0.0))
    reported = content.get("reportedCrar")
    if reported is None:
        return state
    patch = StatePatch(
        nodes_to_add=[
            node(
                "decision:dccb:reported_crar_mismatch",
                "decision",
                "Reported CRAR mismatch detected.",
                "invariant_check",
                "reconcile_crar_mismatch",
                1.0,
                {"invariantId": "DCCB_003_REPORTED_CRAR_MATCH"},
            ),
            node(
                "output:corrected_crar",
                "output",
                f"Proposed corrected CRAR = {computed:.2f}%.",
                "invariant_check",
                "reconcile_crar_mismatch",
                1.0,
                {
                    "addressesOutputs": ["output:crar"],
                    "numeric": True,
                    "lineage": content.get("lineage", {}),
                    "proposedCorrection": True,
                    "finalConfidence": 1.0,
                },
            ),
            node(
                "caveat:dccb:auditor_confirmation",
                "assumption",
                "Requires auditor confirmation before filing or source-system mutation.",
                "invariant_check",
                "reconcile_crar_mismatch",
                0.95,
                {"blocking": True},
            ),
        ],
        edges_to_add=[
            edge("claim:dccb:computed_crar", "output:corrected_crar", "supports"),
            edge("decision:dccb:reported_crar_mismatch", "output:corrected_crar", "produces"),
            edge("caveat:dccb:auditor_confirmation", "output:corrected_crar", "blocks"),
        ],
        artifacts_to_add=[
            {
                "id": "artifact:reconciliation:dccb:reported_crar_mismatch",
                "type": "reconciliation_patch",
                "content": {
                    "diagnosis": "Reported CRAR does not match recomputed CRAR.",
                    "strategy": "propose_correction",
                    "targetInvariantIds": ["DCCB_003_REPORTED_CRAR_MATCH"],
                    "reportedCrar": float(reported),
                    "computedCrar": computed,
                    "suggestedCorrection": f"Replace reported CRAR {float(reported):.2f}% with computed CRAR {computed:.2f}%.",
                    "requiresConfirmation": True,
                    "sourceMutated": False,
                },
                "producedBy": "reconcile_crar_mismatch",
                "timestamp": utc_now(),
            }
        ],
        decisions_to_add=[
            {
                "id": "decision:dccb:reported_crar_mismatch",
                "description": "Reported CRAR mismatch detected",
                "chosen": "propose_correction_without_mutating_source",
                "alternatives": ["mutate_source_csv", "ignore_mismatch", "abort_without_report"],
                "reason": "Audit discipline requires preserving source evidence and proposing a traceable correction.",
                "decidedBy": "reconcile_crar_mismatch",
                "timestamp": utc_now(),
            }
        ],
        motif_support_delta={"reconciliation": 0.35, "feedback": 0.1},
    )
    validation_errors = validate_patch(state, patch)
    if validation_errors:
        state.setdefault("executionLog", []).append(
            {
                "timestamp": utc_now(),
                "phase": "reconcile",
                "event": "reconciliation_failed",
                "details": {"errors": validation_errors},
            }
        )
        return state
    reconciled = apply_patch(state, patch)
    reconciled.setdefault("patchTimeline", []).append(
        _patch_timeline_record(
            "reconcile_crar_mismatch",
            "reconciliation",
            patch,
            True,
            [],
            len(state.get("invariants", [])),
            len(reconciled.get("invariants", [])),
        )
    )
    reconciled["executionLog"].append(
        {
            "timestamp": utc_now(),
            "phase": "reconcile",
            "event": "reconciliation_patch_applied",
            "details": {"artifactId": "artifact:reconciliation:dccb:reported_crar_mismatch"},
        }
    )
    return reconciled


def execute_pass(
    state: dict[str, Any],
    compiler_pass: CompilerPass,
    root: Path,
    store: Path,
) -> tuple[dict[str, Any], PassResult]:
    before_nodes = set(state["graph"]["nodes"])
    before_edges = len(state["graph"]["edges"])
    before_gap = deepcopy(state["motifState"]["gap"])
    started = utc_now()
    precondition_errors = check_pass_preconditions(state, compiler_pass)
    if precondition_errors:
        failed = PassResult("failed", StatePatch(), error="; ".join(precondition_errors))
        state["passHistory"].append(
            {
                "passName": compiler_pass.name,
                "startedAt": started,
                "completedAt": utc_now(),
                "nodesAdded": [],
                "nodesModified": [],
                "edgesAdded": 0,
                "invariantsBefore": len(state.get("invariants", [])),
                "invariantsAfter": len(state.get("invariants", [])),
                "llmCalls": 0,
                "toolCalls": 0,
                "status": "failed",
                "error": failed.error,
                "motifGapBefore": before_gap,
                "motifGapAfter": before_gap,
                "motifGapDelta": {},
            }
        )
        state["status"] = "failed"
        return state, failed
    result = compiler_pass.run(state, root)
    if result.status != "success":
        state["passHistory"].append(
            {
                "passName": compiler_pass.name,
                "startedAt": started,
                "completedAt": utc_now(),
                "nodesAdded": [],
                "nodesModified": [],
                "edgesAdded": 0,
                "invariantsBefore": len(state.get("invariants", [])),
                "invariantsAfter": len(state.get("invariants", [])),
                "llmCalls": result.llm_calls,
                "toolCalls": result.tool_calls,
                "status": result.status,
                "error": result.error,
                "motifGapBefore": before_gap,
                "motifGapAfter": before_gap,
                "motifGapDelta": {},
            }
        )
        state["status"] = "failed"
        return state, result
    validation_errors = validate_patch(state, result.patch)
    validation_errors.extend(
        authorize_patch(result.patch, "domain_pass", state.get("taskAst", {}).get("meta", {}).get("domain"))
    )
    if validation_errors:
        failed = PassResult("failed", result.patch, error="; ".join(validation_errors))
        state.setdefault("patchTimeline", []).append(
            _patch_timeline_record(
                compiler_pass.name,
                "domain_pass",
                result.patch,
                False,
                validation_errors,
                len(state.get("invariants", [])),
                len(state.get("invariants", [])),
            )
        )
        state["status"] = "failed"
        return state, failed
    next_state = apply_patch(state, result.patch)
    invariants = run_invariants(next_state)
    next_state["invariants"] = invariants
    after_gap = deepcopy(next_state["motifState"]["gap"])
    gap_delta = {
        key: round(before_gap.get(key, 0.0) - after_gap.get(key, 0.0), 4)
        for key in MOTIF_KEYS
        if before_gap.get(key, 0.0) != after_gap.get(key, 0.0)
    }
    pass_record = {
        "passName": compiler_pass.name,
        "startedAt": started,
        "completedAt": utc_now(),
        "nodesAdded": sorted(set(next_state["graph"]["nodes"]) - before_nodes),
        "nodesModified": [],
        "edgesAdded": len(next_state["graph"]["edges"]) - before_edges,
        "invariantsBefore": len(state.get("invariants", [])),
        "invariantsAfter": len(invariants),
        "llmCalls": result.llm_calls,
        "toolCalls": result.tool_calls,
        "status": "success",
        "error": None,
        "motifGapBefore": before_gap,
        "motifGapAfter": after_gap,
        "motifGapDelta": gap_delta,
    }
    next_state["passHistory"].append(pass_record)
    next_state.setdefault("patchTimeline", []).append(
        _patch_timeline_record(
            compiler_pass.name,
            "domain_pass",
            result.patch,
            True,
            [],
            len(state.get("invariants", [])),
            len(invariants),
        )
    )
    next_state["executionLog"].append(
        {
            "timestamp": utc_now(),
            "phase": compiler_pass.phase,
            "event": "pass_committed",
            "details": {"passName": compiler_pass.name, "patch": result.patch.to_dict()},
        }
    )
    append_jsonl(store / "logs" / "execution.jsonl", next_state["executionLog"][-1])
    return next_state, result


def run_task(
    request_or_state: str,
    root: Path,
    domain: str | None = None,
    input_files: list[str] | None = None,
    llm_provider: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    store = ensure_store(root)
    candidate = Path(request_or_state)
    if candidate.exists() and candidate.is_file():
        loaded = read_json(candidate)
        state = loaded if "taskAst" in loaded else initial_state(loaded, diagnose(loaded))
    else:
        task_ast = parse_request(request_or_state, domain)
        for location in input_files or []:
            if all(item.get("location") != location for item in task_ast.get("inputs", [])):
                task_ast["inputs"].append(
                    {
                        "id": f"input:{len(task_ast['inputs']) + 1}",
                        "label": Path(location).name,
                        "type": "repo" if Path(location).is_dir() else "code" if str(location).endswith(".patch") else "data",
                        "location": location,
                        "resolved": False,
                    }
                )
        llm_calls = []
        if llm_provider in {"mock", "deepseek"}:
            client = MockLLMClient() if llm_provider == "mock" else DeepSeekLLMClient()
            parsed, record = client.call_structured(
                StructuredCallSpec(
                    "CALL_PARSE",
                    {},
                    {"type": "object", "required": ["id", "goal", "intent"]},
                    0.0,
                    1,
                    fallback=lambda payload: payload["fallbackTaskAst"],
                ),
                {"request": request_or_state, "fallbackTaskAst": task_ast},
            )
            task_ast = parsed
            llm_calls.append(record)
            motif, record = client.call_structured(
                StructuredCallSpec(
                    "CALL_DIAGNOSE",
                    {},
                    {"type": "object", "required": ["representation", "invariant"]},
                    0.0,
                    1,
                    fallback=lambda payload: payload["fallbackMotifVector"],
                ),
                {"taskAst": task_ast, "fallbackMotifVector": diagnose(task_ast)},
            )
            state = initial_state(task_ast, motif)
            state["llmCalls"] = llm_calls + [record]
        else:
            state = initial_state(task_ast, diagnose(task_ast))
    state.setdefault("llmCalls", [])
    profile = load_domain_profile(root, state["taskAst"].get("meta", {}).get("domain"))
    state["domainProfile"] = profile
    graph_errors = validate_pass_graph(profile)
    if graph_errors:
        state["invariants"] = graph_errors
        state["status"] = "committed_failed"
        _commit_id, state = commit_state(
            store,
            state,
            status="committed_failed",
            reason=", ".join(item["invariantId"] for item in graph_errors),
            failure_class=classify_failure(item["invariantId"] for item in graph_errors),
        )
        return state
    pass_effects = load_pass_effects(root)
    state["motifFrame"] = create_motif_frame(
        state["taskAst"],
        state["motifState"]["required"],
        state["motifState"]["supported"],
    )
    plan = compile_reasoning_plan(state["taskAst"], state["motifFrame"], registry(), pass_effects)
    state["reasoningPlan"] = plan
    state["reasoningPlans"] = [plan]
    state["verificationPolicy"] = plan["verificationPolicy"]
    by_name = {item.name: item for item in registry()}
    passes = [by_name[name] for name in plan["selectedPasses"] if name in by_name]
    state["artifacts"].append(
        {
            "id": "artifact:pass_plan",
            "type": "pass_plan",
            "content": {
                "passes": [item.name for item in passes],
                "motifFrameId": state["motifFrame"]["id"],
                "reasoningPlanId": plan["id"],
                "verificationPolicy": plan["verificationPolicy"],
                "expectedMotifGapReduction": plan["expectedMotifGapReduction"],
                "rationale": plan["rationale"],
            },
            "producedBy": "motif_compiler",
            "timestamp": utc_now(),
        }
    )
    if dry_run:
        state["status"] = "planning"
        state["executionLog"].append(
            {
                "timestamp": utc_now(),
                "phase": "plan",
                "event": "dry_run_plan",
                "details": {"passes": [item.name for item in passes]},
            }
        )
        write_json(store / "state" / "current.json", state)
        return state
    for compiler_pass in passes:
        state, result = execute_pass(state, compiler_pass, root, store)
        if verbose:
            print(f"{compiler_pass.name}: {result.status}")
        if result.status == "failed":
            break
    state["invariants"] = run_invariants(state)
    schema_errors = validate_cognitive_state(state)
    if schema_errors:
        state["invariants"].append(
            {
                "invariantId": "SCHEMA_001_COGNITIVE_STATE_VALID",
                "passed": False,
                "severity": "error",
                "message": "; ".join(schema_errors),
                "evidence": [],
                "autoFixable": False,
                "suggestedFix": None,
            }
        )
    fatal = [
        item
        for item in state["invariants"]
        if not item.get("passed") and item.get("severity") == "error"
    ]
    if fatal:
        failure_class = classify_failure(item.get("invariantId", "unknown") for item in fatal)
        state = apply_reconciliation(state, fatal)
        state["invariants"] = run_invariants(state)
        state = replan_after_failure(state, failure_class, fatal)
        state = emit_llm_narrative(state, llm_provider)
        reason = ", ".join(item.get("invariantId", "unknown") for item in fatal)
        _commit_id, state = commit_state(
            store,
            state,
            status="committed_failed",
            reason=reason,
            failure_class=failure_class,
        )
    else:
        state = emit_llm_narrative(state, llm_provider)
        _commit_id, state = commit_state(store, state, status="committed_success")
    return state
