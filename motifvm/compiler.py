from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .model import MOTIF_KEYS, PHASE_ORDER, CompilerPass, empty_motif_vector
from .storage import utc_now


CONSEQUENCE_BY_DOMAIN = {
    "dccb_audit": {
        "invariant": 1.0,
        "authority": 0.95,
        "terminal_state": 0.95,
        "reconciliation": 0.9,
        "addressing": 0.85,
        "boundary": 0.8,
    },
    "code_review": {
        "boundary": 1.0,
        "invariant": 0.95,
        "authority": 0.8,
        "addressing": 0.85,
        "terminal_state": 0.9,
        "reconciliation": 0.55,
    },
    "default": {
        "representation": 0.55,
        "composition": 0.45,
        "terminal_state": 0.55,
        "scarcity": 0.65,
    },
}


def load_pass_effects(root: Path) -> dict[str, Any]:
    candidates = [root / "config" / "pass_effects.json", Path(__file__).resolve().parents[1] / "config" / "pass_effects.json"]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def create_motif_frame(task_ast: dict[str, Any], required: dict[str, float], supported: dict[str, float]) -> dict[str, Any]:
    gap = _gap(required, supported)
    consequence = _consequence(task_ast)
    risk = {key: round(gap.get(key, 0.0) * consequence.get(key, 0.5), 4) for key in MOTIF_KEYS}
    policies = _policies_from_risk(risk, task_ast)
    return {
        "id": f"motif_frame:{uuid.uuid4().hex[:10]}",
        "taskId": task_ast.get("id"),
        "required": required,
        "supported": supported,
        "gap": gap,
        "risk": risk,
        "selectedPolicies": policies,
        "createdBy": "motif_compiler",
        "updatedAt": utc_now(),
    }


def compile_reasoning_plan(
    task_ast: dict[str, Any],
    motif_frame: dict[str, Any],
    passes: list[CompilerPass],
    pass_effects: dict[str, Any],
) -> dict[str, Any]:
    missing = [
        item.name
        for item in passes
        if item.name not in pass_effects and not pass_effects.get(item.name, {}).get("runtimeInternal")
    ]
    if missing:
        raise ValueError(f"Missing PassEffect metadata: {', '.join(sorted(missing))}")
    selected = _select_passes(task_ast, motif_frame, passes, pass_effects)
    expected = _expected_reduction(selected, pass_effects)
    verification = select_verification_policy(motif_frame)
    return {
        "id": f"reasoning_plan:{uuid.uuid4().hex[:10]}",
        "taskId": task_ast.get("id"),
        "motifFrameId": motif_frame.get("id"),
        "selectedPasses": [item.name for item in selected],
        "modelPolicy": _model_policy(motif_frame),
        "toolPolicy": _tool_policy(motif_frame),
        "verificationPolicy": verification,
        "checkpointPolicy": _checkpoint_policy(motif_frame),
        "reconciliationPolicy": _reconciliation_policy(motif_frame),
        "expectedMotifGapReduction": expected,
        "rationale": _rationale(task_ast, motif_frame, selected, verification),
        "createdAt": utc_now(),
    }


def select_verification_policy(motif_frame: dict[str, Any]) -> dict[str, Any]:
    risk = motif_frame.get("risk", {})
    selected = "standard"
    reasons = []
    max_risk = max(risk.values() or [0.0])
    if risk.get("invariant", 0.0) >= 0.7 or risk.get("authority", 0.0) >= 0.65 or risk.get("reconciliation", 0.0) >= 0.65:
        selected = "strict"
        reasons.append("high invariant/authority/reconciliation risk")
    elif max_risk <= 0.25 or (risk.get("scarcity", 0.0) >= 0.45 and max_risk < 0.65):
        selected = "light"
        reasons.append("low-risk or scarcity-dominant profile without safety-critical risk")
    else:
        reasons.append("standard motif risk profile")
    checks = {
        "light": ["schema", "terminal"],
        "standard": ["schema", "terminal", "lineage", "authority", "domain_invariants"],
        "strict": ["schema", "terminal", "lineage", "authority", "domain_invariants", "contradiction_scan", "confidence_propagation", "pack_verifier"],
    }[selected]
    return {"strength": selected, "checks": checks, "rationale": "; ".join(reasons)}


def replan_after_failure(state: dict[str, Any], failure_class: str | None, failures: list[dict[str, Any]]) -> dict[str, Any]:
    if not failure_class:
        return state
    action_by_failure = {
        "lineage_missing": ("request_more_evidence", {"addressing": 0.25, "state": 0.2}),
        "authority_missing": ("load_authority_sources", {"authority": 0.35, "invariant": 0.15}),
        "reconciliation_required": ("run_reconciliation", {"reconciliation": 0.35, "feedback": 0.15}),
        "computation_blocked": ("request_more_evidence", {"state": 0.25, "addressing": 0.2}),
        "input_invalid": ("commit_failure_request_clean_input", {"addressing": 0.2}),
        "security_risk_detected": ("commit_security_failure", {"boundary": 0.2, "invariant": 0.2}),
    }
    if failure_class not in action_by_failure:
        return state
    action, adjustments = action_by_failure[failure_class]
    frame = dict(state.get("motifFrame", {}))
    risk = dict(frame.get("risk", {}))
    gap = dict(frame.get("gap", {}))
    for key, value in adjustments.items():
        risk[key] = min(1.0, round(risk.get(key, 0.0) + value, 4))
        gap[key] = min(1.0, round(gap.get(key, 0.0) + value, 4))
    frame["risk"] = risk
    frame["gap"] = gap
    frame["updatedAt"] = utc_now()
    state["motifFrame"] = frame
    event = {
        "id": f"replan:{uuid.uuid4().hex[:10]}",
        "failureClass": failure_class,
        "failedInvariants": [item.get("invariantId") for item in failures],
        "action": action,
        "motifAdjustments": adjustments,
        "createdAt": utc_now(),
    }
    state.setdefault("replanEvents", []).append(event)
    prior = state.get("reasoningPlan", {})
    replan = dict(prior)
    replan["id"] = f"reasoning_plan:{uuid.uuid4().hex[:10]}"
    replan["parentPlanId"] = prior.get("id")
    replan["motifFrameId"] = frame.get("id")
    replan["replanReason"] = failure_class
    replan["replanAction"] = action
    replan["createdAt"] = utc_now()
    state.setdefault("reasoningPlans", []).append(replan)
    state["reasoningPlan"] = replan
    state.setdefault("patchTimeline", []).append(
        {
            "passName": "motif_compiler_replan",
            "role": "runtime",
            "authorized": True,
            "authorizationErrors": [],
            "nodesAdded": [],
            "nodesUpdated": [],
            "edgesAdded": [],
            "artifactsAdded": [],
            "decisionsAdded": [event["id"]],
            "motifSupportDelta": adjustments,
            "invariantsBefore": len(state.get("invariants", [])),
            "invariantsAfter": len(state.get("invariants", [])),
            "timestamp": utc_now(),
        }
    )
    return state


def _select_passes(
    task_ast: dict[str, Any],
    motif_frame: dict[str, Any],
    passes: list[CompilerPass],
    pass_effects: dict[str, Any],
) -> list[CompilerPass]:
    domain = task_ast.get("meta", {}).get("domain")
    has_inputs = bool(task_ast.get("inputs"))
    gap = motif_frame.get("gap", {})
    risk = motif_frame.get("risk", {})
    by_name = {item.name: item for item in passes}
    selected_names = {"normalize_intent", "decompose_task", "assign_tools", "schedule_execution", "execute_subtasks", "synthesize_output"}
    if has_inputs:
        selected_names.update({"resolve_inputs", "build_evidence_graph"})
    if domain in {"dccb_audit", "code_review"} or risk.get("authority", 0.0) >= 0.25 or risk.get("invariant", 0.0) >= 0.35:
        selected_names.update({"extract_constraints", "verify_structural"})
    if domain == "code_review" and "summarize" in task_ast.get("goal", "").lower() and risk.get("boundary", 0.0) < 0.7:
        selected_names.discard("extract_constraints")
    light_policy = select_verification_policy(motif_frame)["strength"] == "light"
    for item in passes:
        if not has_inputs and item.name in {"resolve_inputs", "build_evidence_graph"}:
            continue
        if light_policy and item.name == "extract_constraints":
            continue
        score = _pass_score(item, gap, pass_effects)
        if score > 0.08:
            selected_names.add(item.name)
    for name in list(selected_names):
        _include_dependencies(name, by_name, selected_names)
    return _order_selected(selected_names, by_name, gap, pass_effects)


def _include_dependencies(pass_name: str, by_name: dict[str, CompilerPass], selected_names: set[str]) -> None:
    item = by_name.get(pass_name)
    if not item:
        return
    for dep in item.depends_on:
        selected_names.add(dep)
        _include_dependencies(dep, by_name, selected_names)


def _order_selected(
    selected_names: set[str],
    by_name: dict[str, CompilerPass],
    gap: dict[str, float],
    pass_effects: dict[str, Any],
) -> list[CompilerPass]:
    remaining = [by_name[name] for name in selected_names if name in by_name]
    ordered: list[CompilerPass] = []
    emitted: set[str] = set()
    while remaining:
        ready = [item for item in remaining if all(dep in emitted or dep not in selected_names for dep in item.depends_on)]
        if not ready:
            ready = remaining[:]
        ready.sort(key=lambda item: (PHASE_ORDER[item.phase], -_pass_score(item, gap, pass_effects), item.name))
        item = ready[0]
        ordered.append(item)
        emitted.add(item.name)
        remaining.remove(item)
    return ordered


def _pass_score(item: CompilerPass, gap: dict[str, float], pass_effects: dict[str, Any]) -> float:
    effect = pass_effects.get(item.name, {})
    strengthens = effect.get("strengthens", item.strengthens)
    cost = effect.get("cost", {})
    cost_penalty = 0.18 * float(cost.get("latency", 0.0)) + 0.1 * float(cost.get("tokens", 0.0)) + 0.2 * float(cost.get("toolRisk", 0.0))
    return round(sum(gap.get(key, 0.0) * float(value) for key, value in strengthens.items()) - cost_penalty, 4)


def _expected_reduction(selected: list[CompilerPass], pass_effects: dict[str, Any]) -> dict[str, float]:
    reduction = empty_motif_vector(0.0)
    for item in selected:
        effect = pass_effects.get(item.name, {})
        for key, value in effect.get("strengthens", item.strengthens).items():
            reduction[key] = min(1.0, round(reduction.get(key, 0.0) + float(value), 4))
    return {key: value for key, value in reduction.items() if value > 0}


def _gap(required: dict[str, float], supported: dict[str, float]) -> dict[str, float]:
    return {key: max(0.0, round(required.get(key, 0.0) - supported.get(key, 0.0), 4)) for key in MOTIF_KEYS}


def _consequence(task_ast: dict[str, Any]) -> dict[str, float]:
    domain = task_ast.get("meta", {}).get("domain") or "default"
    consequence = {key: 0.5 for key in MOTIF_KEYS}
    consequence.update(CONSEQUENCE_BY_DOMAIN.get("default", {}))
    consequence.update(CONSEQUENCE_BY_DOMAIN.get(domain, {}))
    goal = task_ast.get("goal", "").lower()
    if any(word in goal for word in ("security", "risk", "auth", "verify", "audit", "regulatory")):
        consequence.update({"invariant": max(consequence["invariant"], 0.9), "terminal_state": max(consequence["terminal_state"], 0.85)})
    if any(word in goal for word in ("reconcile", "mismatch", "reported")):
        consequence["reconciliation"] = 1.0
    if any(word in goal for word in ("summarize", "summary")) and domain not in {"dccb_audit"}:
        consequence.update({"invariant": 0.35, "authority": 0.25, "scarcity": 0.8})
    return consequence


def _policies_from_risk(risk: dict[str, float], task_ast: dict[str, Any]) -> list[str]:
    policies = []
    if risk.get("addressing", 0.0) >= 0.45:
        policies.append("lineage_strict_mode")
    if risk.get("authority", 0.0) >= 0.45:
        policies.append("authority_required")
    if risk.get("reconciliation", 0.0) >= 0.45:
        policies.append("contradiction_scan")
    if risk.get("invariant", 0.0) >= 0.65:
        policies.append("strict_verification")
    if risk.get("scarcity", 0.0) >= 0.45:
        policies.append("deterministic_first")
    if risk.get("composition", 0.0) >= 0.35:
        policies.append("subtask_dag")
    return policies or ["standard_runtime"]


def _model_policy(motif_frame: dict[str, Any]) -> dict[str, Any]:
    risk = motif_frame.get("risk", {})
    return {
        "strategy": "deterministic_first",
        "llmAllowed": risk.get("scarcity", 0.0) < 0.8,
        "llmRole": "non_critical_narrative_only",
    }


def _tool_policy(motif_frame: dict[str, Any]) -> dict[str, Any]:
    return {"strategy": "bounded_tools", "sourceMutationAllowed": False, "deterministicEvidenceFirst": True}


def _checkpoint_policy(motif_frame: dict[str, Any]) -> dict[str, Any]:
    risk = motif_frame.get("risk", {})
    return {"checkpointAfterEachPass": max(risk.values() or [0.0]) >= 0.65, "recordPatchTimeline": True}


def _reconciliation_policy(motif_frame: dict[str, Any]) -> dict[str, Any]:
    risk = motif_frame.get("risk", {})
    return {"enabled": risk.get("reconciliation", 0.0) >= 0.25, "sourceMutationAllowed": False, "requiresConfirmation": True}


def _rationale(task_ast: dict[str, Any], motif_frame: dict[str, Any], selected: list[CompilerPass], verification: dict[str, Any]) -> str:
    top = sorted(motif_frame.get("risk", {}).items(), key=lambda item: item[1], reverse=True)[:4]
    top_rendered = ", ".join(f"{key}={value:.2f}" for key, value in top)
    return (
        f"Selected {len(selected)} passes for domain {task_ast.get('meta', {}).get('domain') or 'none'} "
        f"using motif risk profile [{top_rendered}] and {verification['strength']} verification."
    )
