from __future__ import annotations

import re
import uuid
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

from .invariants import run_invariants
from .failure import classify_failure
from .llm import DeepSeekLLMClient, MockLLMClient, StructuredCallSpec
from .model import MOTIF_KEYS, PHASE_ORDER, CompilerPass, PassResult, StatePatch, empty_motif_vector
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
    for token in re.findall(r"(?<!\w)([./~\w-]+\.(?:csv|json|txt|xlsx))(?!\w)", request):
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
            {
                "id": "domain_profile:dccb:crar_formula",
                "sourceName": "DCCB audit domain profile - CRAR formula",
                "sourceType": "domain_profile",
                "version": "0.1.3",
                "effectiveDate": None,
                "location": "authority_sources/dccb/crar_rules.md#crar-formula",
                "sourceHash": _file_hash_if_exists("authority_sources/dccb/crar_rules.md"),
                "confidence": 0.8,
            },
            {
                "id": "domain_profile:dccb:crar_threshold",
                "sourceName": "DCCB audit domain profile - CRAR threshold",
                "sourceType": "domain_profile",
                "version": "0.1.3",
                "effectiveDate": None,
                "location": "authority_sources/dccb/crar_rules.md#threshold",
                "sourceHash": _file_hash_if_exists("authority_sources/dccb/crar_rules.md"),
                "confidence": 0.8,
            },
            {
                "id": "domain_profile:dccb:reported_crar_match",
                "sourceName": "DCCB audit domain profile - reported CRAR consistency",
                "sourceType": "domain_profile",
                "version": "0.1.3",
                "effectiveDate": None,
                "location": "authority_sources/dccb/crar_rules.md#reported-value-consistency",
                "sourceHash": _file_hash_if_exists("authority_sources/dccb/crar_rules.md"),
                "confidence": 0.8,
            },
        ]
    elif task_ast.get("meta", {}).get("domain") == "code_review":
        authorities = [
            {
                "id": "authority:code_review:security_policy",
                "sourceName": "Code review security policy",
                "sourceType": "domain_profile",
                "version": "0.1.8",
                "effectiveDate": None,
                "location": "authority_sources/code_review/security_policy.md",
                "sourceHash": _file_hash_if_exists("authority_sources/code_review/security_policy.md"),
                "confidence": 0.8,
            },
            {
                "id": "authority:code_review:review_policy",
                "sourceName": "Code review policy",
                "sourceType": "domain_profile",
                "version": "0.1.8",
                "effectiveDate": None,
                "location": "authority_sources/code_review/security_policy.md",
                "sourceHash": _file_hash_if_exists("authority_sources/code_review/security_policy.md"),
                "confidence": 0.8,
            },
            {
                "id": "authority:code_review:test_policy",
                "sourceName": "Code review test policy",
                "sourceType": "domain_profile",
                "version": "0.1.8",
                "effectiveDate": None,
                "location": "authority_sources/code_review/security_policy.md",
                "sourceHash": _file_hash_if_exists("authority_sources/code_review/security_policy.md"),
                "confidence": 0.7,
            },
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
        "graph": {"nodes": {}, "edges": []},
        "artifacts": [],
        "decisions": [],
        "invariants": [],
        "passHistory": [],
        "executionLog": [],
        "branch": "main",
        "parentCommit": None,
        "status": "planning",
    }


def _file_hash_if_exists(location: str) -> str | None:
    path = Path(location)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_gap(required: dict[str, float], supported: dict[str, float]) -> dict[str, float]:
    return {key: max(0.0, round(required.get(key, 0.0) - supported.get(key, 0.0), 4)) for key in MOTIF_KEYS}


def select_passes(
    passes: list[CompilerPass],
    required: dict[str, float],
    supported: dict[str, float],
    threshold: float = 0.15,
) -> list[CompilerPass]:
    gap = compute_gap(required, supported)
    relevant = {
        item.name
        for item in passes
        if any(gap.get(key, 0.0) >= threshold for key in item.strengthens)
    }
    by_name = {item.name: item for item in passes}

    def include_dependencies(pass_name: str) -> None:
        for dep in by_name[pass_name].depends_on:
            if dep not in relevant and dep in by_name:
                relevant.add(dep)
                include_dependencies(dep)

    for pass_name in list(relevant):
        include_dependencies(pass_name)

    remaining = [item for item in passes if item.name in relevant]
    selected: list[CompilerPass] = []
    selected_names: set[str] = set()
    while remaining:
        ready = [item for item in remaining if all(dep in selected_names for dep in item.depends_on)]
        if not ready:
            break
        ready.sort(
            key=lambda item: (
                PHASE_ORDER[item.phase],
                -sum(gap.get(key, 0.0) for key in item.strengthens),
                item.name,
            )
        )
        item = ready[0]
        selected.append(item)
        selected_names.add(item.name)
        remaining.remove(item)
    return selected


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
                        "type": "code" if str(location).endswith(".patch") else "data",
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
    passes = select_passes(registry(), state["motifState"]["required"], state["motifState"]["supported"])
    state["artifacts"].append(
        {
            "id": "artifact:pass_plan",
            "type": "pass_plan",
            "content": {"passes": [item.name for item in passes]},
            "producedBy": "planner",
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
        state = apply_reconciliation(state, fatal)
        state["invariants"] = run_invariants(state)
        reason = ", ".join(item.get("invariantId", "unknown") for item in fatal)
        _commit_id, state = commit_state(
            store,
            state,
            status="committed_failed",
            reason=reason,
            failure_class=classify_failure(item.get("invariantId", "unknown") for item in fatal),
        )
    else:
        _commit_id, state = commit_state(store, state, status="committed_success")
    return state
