from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import current_state_path, ensure_store, read_json


def load_state(root: Path, state_path: str | None = None) -> dict[str, Any]:
    if state_path:
        return read_json(Path(state_path))
    store = ensure_store(root)
    path = current_state_path(store)
    if not path.exists():
        raise FileNotFoundError("No current state found. Run a task first.")
    return read_json(path)


def render_report(state: dict[str, Any], show_graph: bool = False) -> str:
    task = state.get("taskAst", {})
    motif = state.get("motifState", {})
    required = motif.get("required", {})
    supported = motif.get("supported", {})
    gap = motif.get("gap", {})
    final = next(
        (
            artifact.get("content", {}).get("text")
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "final_output"
        ),
        None,
    )
    lines = [
        "MotifVM Report",
        "==============",
        f"State: {state.get('id')} ({state.get('status')})",
        f"Commit: {state.get('parentCommit') or 'uncommitted'}",
        f"Goal: {task.get('goal')}",
        f"Intent: {task.get('intent')}",
        f"Domain: {task.get('meta', {}).get('domain') or 'none'}",
        "",
        "Terminal State",
        "--------------",
    ]
    lines.extend(_terminal_block(state))
    lines.extend([
        "",
        "Motif Frame",
        "-----------",
    ])
    frame = state.get("motifFrame", {})
    risk = frame.get("risk", {})
    if frame:
        lines.append(f"Frame: {frame.get('id')} by {frame.get('createdBy')}")
        lines.append(f"Policies: {', '.join(frame.get('selectedPolicies', [])) or 'none'}")
        for key, value in sorted(risk.items(), key=lambda item: item[1], reverse=True)[:6]:
            lines.append(
                f"- {key}: required={frame.get('required', {}).get(key, 0):.2f}, "
                f"supported={frame.get('supported', {}).get(key, 0):.2f}, "
                f"gap={frame.get('gap', {}).get(key, 0):.2f}, risk={value:.2f}"
            )
    else:
        lines.append("No motif frame recorded.")
    plan = state.get("reasoningPlan", {})
    verification = plan.get("verificationPolicy") or state.get("verificationPolicy", {})
    lines.extend([
        "",
        "Reasoning Plan",
        "--------------",
    ])
    if plan:
        lines.append(f"Plan: {plan.get('id')}")
        lines.append(f"Selected Passes: {', '.join(plan.get('selectedPasses', []))}")
        if verification:
            lines.append(
                f"Verification: {verification.get('strength')} "
                f"({verification.get('rationale')})"
            )
            lines.append(f"Checks: {', '.join(verification.get('checks', []))}")
        lines.append(f"Rationale: {plan.get('rationale')}")
    else:
        lines.append("No reasoning plan recorded.")
    if state.get("replanEvents"):
        lines.extend(["", "Replanning", "----------"])
        for event in state.get("replanEvents", []):
            lines.append(
                f"- {event.get('failureClass')}: {event.get('action')} "
                f"adjustments={event.get('motifAdjustments')}"
            )
    lines.extend([
        "",
        "Final Output",
        "------------",
        final or "No final output artifact produced.",
        "",
        "Inputs",
        "------",
    ])
    for item in state.get("inputManifest", []):
        lines.append(
            f"- {item.get('inputId')}: {item.get('path')} "
            f"sha256={str(item.get('sha256', ''))[:12]} rows={item.get('rowsRead')}"
        )
    adapter_outputs = [artifact for artifact in state.get("artifacts", []) if artifact.get("type") == "adapter_output"]
    lines.extend(["", "Adapters", "--------"])
    if adapter_outputs:
        for artifact in adapter_outputs:
            content = artifact.get("content", {})
            lines.append(
                f"- {content.get('adapterId')} v{content.get('adapterVersion')} "
                f"facts={len(content.get('extractedFacts', []))} evidence={len(content.get('evidenceRefs', []))}"
            )
    else:
        lines.append("- none")
    lines.extend([
        "",
        "Authority",
        "---------",
    ])
    for authority in state.get("authorityRefs", []):
        section = authority.get("sectionId") or "unsectioned"
        excerpt = authority.get("quotedRuleExcerpt")
        lines.append(f"- {authority.get('id')} ({authority.get('sourceType')}, v{authority.get('version')}, {section})")
        if excerpt:
            lines.append(f"  rule: {excerpt}")
    lines.extend([
        "",
        "Motif Gap",
        "---------",
    ])
    top_gap = sorted(gap.items(), key=lambda item: item[1], reverse=True)[:8]
    for key, value in top_gap:
        lines.append(
            f"- {key}: required={required.get(key, 0):.2f}, "
            f"supported={supported.get(key, 0):.2f}, gap={value:.2f}"
        )
    lines.extend(["", "Pass History", "------------"])
    for record in state.get("passHistory", []):
        lines.append(
            f"- {record['passName']}: {record['status']} "
            f"(nodes +{len(record.get('nodesAdded', []))}, edges +{record.get('edgesAdded', 0)})"
        )
        deltas = {
            key: value
            for key, value in record.get("motifGapDelta", {}).items()
            if value > 0
        }
        if deltas:
            rendered = ", ".join(
                f"{key} {record['motifGapBefore'].get(key, 0):.2f}->{record['motifGapAfter'].get(key, 0):.2f}"
                for key in sorted(deltas)
            )
            lines.append(f"  motif gaps: {rendered}")
    timeline = state.get("patchTimeline", [])
    lines.extend(["", "Patch Timeline", "--------------"])
    if timeline:
        for item in timeline:
            status = "authorized" if item.get("authorized") else "rejected"
            lines.append(
                f"- {item.get('passName')} [{item.get('role')}, {status}]: "
                f"nodes +{len(item.get('nodesAdded', []))}, "
                f"edges +{len(item.get('edgesAdded', []))}, "
                f"artifacts +{len(item.get('artifactsAdded', []))}"
            )
    else:
        lines.append("- none")
    claims = _claims(state)
    if claims:
        lines.extend(["", "Claims", "------"])
        lines.extend(claims)
    lines.extend(["", "Invariants", "----------"])
    for item in state.get("invariants", []):
        mark = "PASS" if item.get("passed") else item.get("severity", "FAIL").upper()
        lines.append(f"- {mark} {item.get('invariantId')}: {item.get('message')}")
    lineage = _crar_lineage(state)
    if lineage:
        lines.extend(["", "CRAR Lineage", "------------"])
        lines.extend(lineage)
    reconciliation = _reconciliation_summary(state)
    if reconciliation:
        lines.extend(["", "Reconciliation", "--------------"])
        lines.extend(reconciliation)
    lines.extend(["", "LLM Calls", "---------"])
    if state.get("llmCalls"):
        for call in state.get("llmCalls", []):
            lines.append(
                f"- {call.get('callType')} {call.get('schemaStatus')} "
                f"model={call.get('model')} retries={call.get('retryCount')}"
            )
    else:
        lines.append("- none")
    caveats = _caveats(state)
    if caveats:
        lines.extend(["", "Caveats", "-------"])
        lines.extend(caveats)
    lines.extend(["", "Artifacts", "---------"])
    for artifact in state.get("artifacts", []):
        lines.append(f"- {artifact.get('id')} [{artifact.get('type')}] by {artifact.get('producedBy')}")
    if show_graph:
        lines.extend(["", "Graph", "-----"])
        lines.append(f"Nodes: {len(state.get('graph', {}).get('nodes', {}))}")
        lines.append(f"Edges: {len(state.get('graph', {}).get('edges', []))}")
        for node_id, node in state.get("graph", {}).get("nodes", {}).items():
            lines.append(f"- {node_id} ({node.get('type')}): {node.get('content')}")
    return "\n".join(lines)


def _claims(state: dict[str, Any]) -> list[str]:
    lines = []
    for node_id, node in state.get("graph", {}).get("nodes", {}).items():
        if node.get("type") == "claim":
            lines.append(f"- {node_id}: {node.get('content')} confidence={node.get('confidence')}")
    return lines


def _caveats(state: dict[str, Any]) -> list[str]:
    lines = []
    for node_id, node in state.get("graph", {}).get("nodes", {}).items():
        if node.get("type") == "assumption" and node.get("meta", {}).get("blocking"):
            lines.append(f"- {node_id}: {node.get('content')}")
    return lines


def _crar_lineage(state: dict[str, Any]) -> list[str]:
    crar = next(
        (
            artifact
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "dccb_crar_computation"
        ),
        None,
    )
    if not crar:
        return []
    nodes = state.get("graph", {}).get("nodes", {})
    content = crar.get("content", {})
    lineage = content.get("lineage", {})
    lines = [
        f"- claim: {lineage.get('claimNodeId', 'unknown')}",
        f"- computation artifact: {lineage.get('computationArtifactId', crar.get('id'))}",
    ]
    for evidence_id in lineage.get("evidenceNodeIds", []):
        evidence = nodes.get(evidence_id, {})
        meta = evidence.get("meta", {})
        label = meta.get("component", evidence_id)
        row = meta.get("rowNumber", "?")
        amount = meta.get("amount", "?")
        lines.append(f"- evidence: {label} row {row} amount {amount} ({evidence_id})")
    for invariant_id in lineage.get("invariantIds", []):
        status = next(
            (
                "PASS" if item.get("passed") else item.get("severity", "FAIL").upper()
                for item in state.get("invariants", [])
                if item.get("invariantId") == invariant_id
            ),
            "not run",
        )
        lines.append(f"- invariant: {invariant_id} [{status}]")
    reported = content.get("reportedCrar")
    if reported is not None:
        computed = content.get("computedCrar")
        lines.append(f"- reported vs computed: {float(reported):.2f}% vs {float(computed):.2f}%")
    return lines


def _terminal_block(state: dict[str, Any]) -> list[str]:
    lines = [
        f"Status: {state.get('status')}",
        f"Reason: {state.get('terminalReason') or 'none'}",
        f"Failure Class: {state.get('failureClass') or 'none'}",
    ]
    crar = next(
        (
            artifact
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "dccb_crar_computation"
        ),
        None,
    )
    validation = next(
        (
            artifact
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "dccb_crar_input_validation"
        ),
        None,
    )
    reconciliation = next(
        (
            artifact
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "reconciliation_patch"
        ),
        None,
    )
    if crar:
        content = crar.get("content", {})
        computed = content.get("computedCrar")
        reported = content.get("reportedCrar")
        lines.append(f"Computed CRAR: {float(computed):.2f}%")
        if reported is not None:
            difference = abs(float(reported) - float(computed))
            lines.append(f"Reported CRAR: {float(reported):.2f}%")
            lines.append(f"Difference: {difference:.2f} percentage points")
        lines.append(
            "Correction Proposed: Yes" if reconciliation else "Correction Proposed: No"
        )
    elif validation:
        lines.append(f"Blocked: {validation.get('content', {}).get('message')}")
        lines.append("Correction Proposed: No")
    if reconciliation:
        content = reconciliation.get("content", {})
        lines.append("Source Mutated: Yes" if content.get("sourceMutated") else "Source Mutated: No")
        lines.append(
            "Auditor Confirmation Required: Yes"
            if content.get("requiresConfirmation")
            else "Auditor Confirmation Required: No"
        )
    return lines


def _reconciliation_summary(state: dict[str, Any]) -> list[str]:
    patches = [
        artifact
        for artifact in state.get("artifacts", [])
        if artifact.get("type") == "reconciliation_patch"
    ]
    if not patches:
        return []
    lines = []
    for patch in patches:
        content = patch.get("content", {})
        lines.append(f"- diagnosis: {content.get('diagnosis')}")
        lines.append(f"- strategy: {content.get('strategy')}")
        lines.append(f"- suggestion: {content.get('suggestedCorrection')}")
        lines.append(
            "- confirmation: required"
            if content.get("requiresConfirmation")
            else "- confirmation: not required"
        )
    return lines
