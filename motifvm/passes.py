from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any

from .adapters import adapt_path
from .model import CompilerPass, PassResult, StatePatch
from .storage import utc_now


def node(
    node_id: str,
    node_type: str,
    content: str,
    source: str,
    created_by: str,
    confidence: float = 0.8,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "content": content,
        "status": "resolved",
        "confidence": confidence,
        "source": source,
        "createdBy": created_by,
        "createdAt": utc_now(),
        "meta": meta or {},
    }


def edge(source: str, target: str, relation: str, weight: float = 1.0) -> dict[str, Any]:
    return {"from": source, "to": target, "relation": relation, "weight": weight}


def normalize_intent(state: dict[str, Any], root: Path) -> PassResult:
    goal = state["taskAst"]["goal"].strip()
    normalized = re.sub(r"\s+", " ", goal)
    patch = StatePatch(
        nodes_to_add=[
            node("goal:root", "goal", normalized, "user", "normalize_intent", 0.95)
        ],
        task_updates={"goal": normalized},
        status_update="planning",
        motif_support_delta={"representation": 0.35, "boundary": 0.15},
    )
    return PassResult("success", patch)


def resolve_inputs(state: dict[str, Any], root: Path) -> PassResult:
    inputs = state["taskAst"].get("inputs", [])
    nodes = []
    artifacts = []
    updated_inputs = []
    for input_ref in inputs:
        item = dict(input_ref)
        location = item.get("location", "")
        path = Path(location)
        if not path.is_absolute():
            path = root / path
        resolved = path.exists()
        item["resolved"] = resolved
        item["location"] = str(path)
        updated_inputs.append(item)
        nodes.append(
            node(
                f"input:{item['id']}",
                "evidence" if resolved else "error",
                f"Resolved input {item['label']} at {path}"
                if resolved
                else f"Input {item['label']} was not found at {path}",
                "tool",
                "resolve_inputs",
                1.0 if resolved else 0.4,
                {"inputRef": item["id"], "path": str(path), "exists": resolved},
            )
        )
        if resolved:
            adapter_result = adapt_path(item, path)
            if adapter_result is None:
                digest = _tree_hash(path) if path.is_dir() else _sha256(path)
                rows_read = _count_csv_rows(path) if path.is_file() and path.suffix.lower() == ".csv" else None
                artifacts.append(
                    {
                        "id": f"artifact:input:{item['id']}",
                        "type": "resolved_input",
                        "content": {
                            "inputId": item["id"],
                            "path": str(path),
                            "sha256": digest,
                            "rowsRead": rows_read,
                            "kind": "repo" if path.is_dir() else "file",
                            "readAt": utc_now(),
                        },
                        "producedBy": "resolve_inputs",
                        "timestamp": utc_now(),
                    }
                )
            else:
                adapter_artifact = adapter_result.to_artifact()
                adapter_artifact["timestamp"] = utc_now()
                artifacts.extend(adapter_result.resolved_artifacts)
                artifacts.append(adapter_artifact)
    patch = StatePatch(
        nodes_to_add=nodes,
        edges_to_add=[edge(f"input:{i['id']}", "goal:root", "supports") for i in updated_inputs],
        artifacts_to_add=artifacts,
        task_updates={"inputs": updated_inputs},
        motif_support_delta={"addressing": 0.45, "storage": 0.25, "state": 0.15},
    )
    return PassResult("success", patch, tool_calls=len(inputs))


def decompose_task(state: dict[str, Any], root: Path) -> PassResult:
    task_ast = state["taskAst"]
    domain = task_ast.get("meta", {}).get("domain")
    if domain == "dccb_audit" and "crar" in task_ast["goal"].lower():
        goals = [
            "Read CRAR source data",
            "Extract Tier I, Tier II, and RWA values",
            "Compute CRAR",
            "Verify formula and threshold",
            "Emit audit report",
        ]
    elif domain == "code_review":
        goals = [
            "Read reviewed diff",
            "Extract changed lines",
            "Check security review invariants",
            "Classify review risk",
            "Emit review report",
        ]
    else:
        goals = [
            "Clarify objective",
            "Gather evidence",
            "Apply relevant checks",
            "Emit result",
        ]
    subtasks = []
    nodes = []
    previous = None
    edges = []
    input_ids = [item["id"] for item in task_ast.get("inputs", [])]
    output_ids = [item["id"] for item in task_ast.get("requiredOutputs", [])]
    for index, goal in enumerate(goals, start=1):
        task_id = f"task:{index}"
        subtasks.append(
            {
                "id": task_id,
                "goal": goal,
                "dependsOn": [previous] if previous else [],
                "inputs": input_ids,
                "outputs": output_ids if index == len(goals) else [],
                "status": "pending",
                "assignedPass": None,
            }
        )
        nodes.append(node(task_id, "subtask", goal, "pass", "decompose_task", 0.85))
        edges.append(edge("goal:root", task_id, "decomposes_to"))
        if previous:
            edges.append(edge(previous, task_id, "depends_on"))
        previous = task_id
    patch = StatePatch(
        nodes_to_add=nodes,
        edges_to_add=edges,
        task_updates={"subtasks": subtasks},
        motif_support_delta={"composition": 0.4, "hierarchy": 0.35},
    )
    return PassResult("success", patch)


def extract_constraints(state: dict[str, Any], root: Path) -> PassResult:
    domain = state["taskAst"].get("meta", {}).get("domain")
    constraints = list(state["taskAst"].get("constraints", []))
    if domain == "dccb_audit":
        constraints.extend(
            [
                {
                    "id": "constraint:dccb:formula",
                    "description": "CRAR must use (Tier I + Tier II) / RWA * 100.",
                    "type": "hard",
                    "source": "domain",
                    "verifiable": True,
                    "verifier": "DCCB_001_FORMULA",
                },
                {
                    "id": "constraint:dccb:threshold",
                    "description": "Computed CRAR should meet or exceed the configured threshold.",
                    "type": "hard",
                    "source": "domain",
                    "verifiable": True,
                    "verifier": "DCCB_002_THRESHOLD",
                },
                {
                    "id": "constraint:dccb:reported_match",
                    "description": "Reported CRAR should match recomputed CRAR when a reported value is provided.",
                    "type": "hard",
                    "source": "domain",
                    "verifiable": True,
                    "verifier": "DCCB_003_REPORTED_CRAR_MATCH",
                },
            ]
        )
    elif domain == "code_review":
        constraints.extend(
            [
                {
                    "id": "constraint:code:no_auth_bypass",
                    "description": "Authorization-sensitive functions must not unconditionally allow access.",
                    "type": "hard",
                    "source": "domain",
                    "verifiable": True,
                    "verifier": "CODE_003_NO_UNCONDITIONAL_AUTH_ALLOW",
                },
                {
                    "id": "constraint:code:no_secret_literal",
                    "description": "Added lines must not contain obvious secrets, tokens, or passwords.",
                    "type": "hard",
                    "source": "domain",
                    "verifiable": True,
                    "verifier": "CODE_004_NO_SECRET_LITERAL",
                },
            ]
        )
    nodes = [
        node(
            item["id"],
            "constraint",
            item["description"],
            item["source"],
            "extract_constraints",
            0.9,
            {"verifier": item.get("verifier")},
        )
        for item in constraints
    ]
    patch = StatePatch(
        nodes_to_add=nodes,
        edges_to_add=[edge(item["id"], "goal:root", "supports") for item in constraints],
        task_updates={"constraints": constraints},
        motif_support_delta={"invariant": 0.35, "authority": 0.25, "boundary": 0.2},
    )
    return PassResult("success", patch)


def build_evidence_graph(state: dict[str, Any], root: Path) -> PassResult:
    nodes = []
    edges = []
    for artifact in state.get("artifacts", []):
        if artifact.get("type") != "adapter_output":
            continue
        content = artifact.get("content", {})
        adapter_id = content.get("adapterId", "")
        if adapter_id == "adapter:csv:v0.5":
            path = Path(content.get("path", "input.csv"))
            nodes.append(
                node(
                    f"evidence:csv:{path.stem}",
                    "evidence",
                    f"CSV adapter extracted {len(content.get('extractedFacts', []))} fact(s).",
                    "artifact_adapter",
                    "build_evidence_graph",
                    1.0,
                    {
                        "path": str(path),
                        "rowCount": len(content.get("extractedFacts", [])),
                        "artifactId": artifact["id"],
                        "inputHash": content.get("contentHash"),
                        "inputRef": content.get("inputId"),
                    },
                )
            )
        elif adapter_id == "adapter:repo:v0.5":
            path = Path(content.get("path", "repo"))
            nodes.append(
                node(
                    f"evidence:repo:{path.name}",
                    "evidence",
                    f"Repository adapter extracted {len(content.get('extractedFacts', []))} fact(s).",
                    "artifact_adapter",
                    "build_evidence_graph",
                    1.0,
                    {
                        "path": str(path),
                        "artifactId": artifact["id"],
                        "inputHash": content.get("contentHash"),
                        "inputRef": content.get("inputId"),
                        "changedFiles": content.get("metadata", {}).get("changedFiles", []),
                    },
                )
            )
        for evidence_ref in content.get("evidenceRefs", []):
            meta = dict(evidence_ref.get("metadata", {}))
            meta.update(
                {
                    "evidenceRef": evidence_ref,
                    "inputHash": evidence_ref.get("inputHash"),
                    "inputRef": evidence_ref.get("inputId"),
                }
            )
            if evidence_ref.get("locatorType") == "row":
                meta.setdefault("rowNumber", evidence_ref.get("locator"))
                meta.setdefault("component", evidence_ref.get("metadata", {}).get("component"))
                content_text = f"CSV row {evidence_ref.get('locator')}: {evidence_ref.get('excerpt')}"
            elif evidence_ref.get("locatorType") == "line":
                meta.setdefault("rowNumber", evidence_ref.get("metadata", {}).get("newLine"))
                content_text = f"Added line {evidence_ref.get('locator')}: {evidence_ref.get('excerpt')}"
            else:
                content_text = f"Evidence {evidence_ref.get('locator')}: {evidence_ref.get('excerpt')}"
            nodes.append(
                node(
                    evidence_ref["id"],
                    "evidence",
                    content_text,
                    "artifact_adapter",
                    "build_evidence_graph",
                    1.0,
                    meta,
                )
            )
            edges.append(edge(evidence_ref["id"], "goal:root", "supports"))
        facts = content.get("extractedFacts", [])
        if facts:
            nodes.append(
                node(
                    f"facts:{content.get('inputId')}",
                    "evidence",
                    f"Adapter extracted {len(facts)} normalized fact(s).",
                    "artifact_adapter",
                    "build_evidence_graph",
                    1.0,
                    {"adapterId": content.get("adapterId"), "factCount": len(facts)},
                )
            )
    for artifact in state.get("artifacts", []):
        if artifact.get("type") == "repo_review_input":
            continue
        if artifact.get("type") != "resolved_input":
            continue
        if artifact.get("producedBy") == "artifact_adapter":
            continue
        path = Path(artifact["content"]["path"])
        input_hash = artifact["content"].get("sha256")
        input_ref = artifact["content"].get("inputId")
        if path.suffix.lower() != ".csv":
            if path.suffix.lower() == ".patch":
                diff_nodes, diff_edges = _diff_evidence_nodes(path, input_ref, input_hash)
                nodes.extend(diff_nodes)
                edges.extend(diff_edges)
            continue
        rows = _read_csv_rows(path)
        artifact_id = f"artifact:csv:{path.stem}"
        component_nodes = []
        component_edges = []
        for index, row in enumerate(rows, start=2):
            component = (row.get("component") or row.get("name") or "").strip().lower()
            amount = row.get("amount") or row.get("value")
            if not component:
                continue
            component_id = f"evidence:csv:{path.stem}:{component}"
            evidence_ref = {
                "id": component_id,
                "inputId": input_ref,
                "inputHash": input_hash,
                "locatorType": "row",
                "locator": str(index),
                "excerpt": f"{component},{amount}",
            }
            component_nodes.append(
                node(
                    component_id,
                    "evidence",
                    f"CSV row {index}: {component} = {amount}",
                    "tool",
                    "build_evidence_graph",
                    1.0,
                    {
                        "path": str(path),
                        "rowNumber": index,
                        "component": component,
                        "amount": amount,
                        "artifactId": artifact_id,
                        "inputHash": input_hash,
                        "inputRef": input_ref,
                        "evidenceRef": evidence_ref,
                    },
                )
            )
            component_edges.append(edge(component_id, f"evidence:csv:{path.stem}", "supports"))
        nodes.append(
            node(
                f"evidence:csv:{path.stem}",
                "evidence",
                f"CSV input contains {len(rows)} data rows.",
                "tool",
                "build_evidence_graph",
                1.0,
                {
                    "path": str(path),
                    "rowCount": len(rows),
                    "artifactId": artifact_id,
                    "inputHash": input_hash,
                    "inputRef": input_ref,
                },
            )
        )
        nodes.extend(component_nodes)
        edges.append(edge(f"evidence:csv:{path.stem}", "goal:root", "supports"))
        edges.extend(component_edges)
    patch = StatePatch(
        nodes_to_add=nodes,
        edges_to_add=edges,
        motif_support_delta={"state": 0.25, "addressing": 0.25, "storage": 0.1},
    )
    return PassResult("success", patch, tool_calls=len(nodes))


def assign_tools(state: dict[str, Any], root: Path) -> PassResult:
    subtasks = []
    decisions = []
    for task in state["taskAst"].get("subtasks", []):
        updated = dict(task)
        goal = task["goal"].lower()
        if "crar" in goal or "tier" in goal or "rwa" in goal:
            updated["assignedPass"] = "compute_crar"
            chosen = "csv_read + math_eval"
        else:
            updated["assignedPass"] = "deterministic_runtime"
            chosen = "deterministic_runtime"
        subtasks.append(updated)
        decisions.append(
            {
                "id": f"decision:tool:{task['id']}",
                "description": f"Assign tool path for {task['goal']}",
                "chosen": chosen,
                "alternatives": ["llm_only", "manual_review"],
                "reason": "Matched task goal to available deterministic capabilities.",
                "decidedBy": "assign_tools",
                "timestamp": utc_now(),
            }
        )
    patch = StatePatch(
        task_updates={"subtasks": subtasks},
        decisions_to_add=decisions,
        motif_support_delta={"transition": 0.25, "scheduling": 0.15},
    )
    return PassResult("success", patch)


def schedule_execution(state: dict[str, Any], root: Path) -> PassResult:
    schedule = [task["id"] for task in state["taskAst"].get("subtasks", [])]
    artifact = {
        "id": "artifact:schedule",
        "type": "pass_schedule",
        "content": {"tasks": schedule},
        "producedBy": "schedule_execution",
        "timestamp": utc_now(),
    }
    patch = StatePatch(
        artifacts_to_add=[artifact],
        motif_support_delta={"scheduling": 0.35, "scarcity": 0.1},
    )
    return PassResult("success", patch)


def execute_subtasks(state: dict[str, Any], root: Path) -> PassResult:
    domain = state["taskAst"].get("meta", {}).get("domain")
    goal = state["taskAst"].get("goal", "").lower()
    if domain == "dccb_audit" and "crar" in goal:
        return _execute_crar(state)
    if domain == "code_review":
        return _execute_code_review(state)
    output_id = state["taskAst"]["requiredOutputs"][0]["id"]
    output = node(
        "output:summary",
        "output",
        f"Executed deterministic MVP path for: {state['taskAst']['goal']}",
        "pass",
        "execute_subtasks",
        0.7,
        {"addressesOutputs": [output_id]},
    )
    patch = StatePatch(
        nodes_to_add=[output],
        edges_to_add=[edge("goal:root", "output:summary", "produces")],
        motif_support_delta={"transition": 0.4, "terminal_state": 0.2},
    )
    return PassResult("success", patch)


def verify_structural(state: dict[str, Any], root: Path) -> PassResult:
    return PassResult(
        "success",
        StatePatch(motif_support_delta={"invariant": 0.25, "feedback": 0.2}),
    )


def synthesize_output(state: dict[str, Any], root: Path) -> PassResult:
    crar = next(
        (
            artifact
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "dccb_crar_computation"
        ),
        None,
    )
    if crar:
        content = crar["content"]
        status = "compliant" if content["computedCrar"] >= content["threshold"] else "non-compliant"
        mismatch = content.get("reportedCrar") is not None and abs(
            content["reportedCrar"] - content["computedCrar"]
        ) > 0.01
        text = (
            f"Computed CRAR is {content['computedCrar']:.2f}% "
            f"using Tier I {content['tier1']:.2f}, Tier II {content['tier2']:.2f}, "
            f"and RWA {content['rwa']:.2f}. Threshold status: {status}."
        )
        if mismatch:
            text += (
                f" Reported CRAR mismatch: reported {content['reportedCrar']:.2f}%, "
                f"computed {content['computedCrar']:.2f}%, "
                f"difference {abs(content['reportedCrar'] - content['computedCrar']):.2f} percentage points."
            )
        addresses = ["output:crar", "output:breakdown", "output:compliance"]
    elif state["taskAst"].get("meta", {}).get("domain") == "code_review":
        review = next(
            (
                artifact
                for artifact in state.get("artifacts", [])
                if artifact.get("type") == "code_review_result"
            ),
            None,
        )
        addresses = [item["id"] for item in state["taskAst"].get("requiredOutputs", [])]
        if review:
            content = review["content"]
            findings = content.get("findings", [])
            text = f"Code review risk: {content['risk']}. Findings: {len(findings)}."
            if findings:
                text += " " + " ".join(f"{f['id']}: {f['message']}" for f in findings)
            meta = {
                "addressesOutputs": addresses,
                "lineage": content.get("lineage", {}),
                "artifactId": review["id"],
            }
        else:
            text = "Code review could not produce a result."
            meta = {"addressesOutputs": addresses}
    else:
        addresses = [item["id"] for item in state["taskAst"].get("requiredOutputs", [])]
        validation = next(
            (
                artifact
                for artifact in state.get("artifacts", [])
                if artifact.get("type") == "dccb_crar_input_validation"
            ),
            None,
        )
        if validation:
            text = f"CRAR computation blocked: {validation['content']['message']}"
            source_stem = Path(validation["content"]["source"]).stem
            meta = {
                "addressesOutputs": addresses,
                "lineage": {
                    "claimNodeId": "error:dccb:crar_input_validation",
                    "evidenceNodeIds": [f"evidence:csv:{source_stem}"],
                    "toolCallIds": ["execute_subtasks"],
                    "inputRefs": [],
                    "invariantIds": ["DCCB_004_CAPITAL_COMPONENTS_PRESENT"],
                    "authorityRefs": ["domain_profile:dccb:crar_formula"],
                    "computationArtifactId": validation["id"],
                },
                "artifactId": validation["id"],
            }
        else:
            text = f"Final output for: {state['taskAst']['goal']}"
            meta = {"addressesOutputs": addresses}
    if crar:
        meta = {"addressesOutputs": addresses}
        meta.update(
            {
                "lineage": crar.get("content", {}).get("lineage", {}),
                "artifactId": crar.get("id"),
            }
        )
    if meta.get("lineage"):
        meta["finalConfidence"] = _lineage_confidence(state, meta["lineage"])
    patch = StatePatch(
        nodes_to_add=[
            node(
                "output:final",
                "output",
                text,
                "pass",
                "synthesize_output",
                0.85,
                meta,
            )
        ],
        edges_to_add=[
            edge("goal:root", "output:final", "produces"),
            edge("claim:dccb:computed_crar", "output:final", "supports")
            if crar
            else edge("claim:code:review_risk", "output:final", "supports")
            if state["taskAst"].get("meta", {}).get("domain") == "code_review"
            else edge("goal:root", "output:final", "supports"),
        ],
        artifacts_to_add=[
            {
                "id": "artifact:final_output",
                "type": "final_output",
                "content": {"text": text},
                "producedBy": "synthesize_output",
                "timestamp": utc_now(),
            }
        ],
        status_update="verifying",
        motif_support_delta={"representation": 0.25, "terminal_state": 0.45},
    )
    return PassResult("success", patch)


def _lineage_confidence(state: dict[str, Any], lineage: dict[str, Any]) -> float:
    nodes = state.get("graph", {}).get("nodes", {})
    confidences = []
    for node_id in [lineage.get("claimNodeId"), *lineage.get("evidenceNodeIds", [])]:
        if node_id in nodes:
            confidences.append(float(nodes[node_id].get("confidence", 1.0)))
    return min(confidences) if confidences else 0.0


def _execute_crar(state: dict[str, Any]) -> PassResult:
    csv_paths = [
        Path(item["location"])
        for item in state["taskAst"].get("inputs", [])
        if item.get("resolved") and Path(item["location"]).suffix.lower() == ".csv"
    ]
    if not csv_paths:
        return PassResult(
            "failed",
            StatePatch(),
            error="No resolved CSV input was available for CRAR computation.",
        )
    values: dict[str, float] = {}
    raw_values: dict[str, str] = {}
    duplicate_keys: set[str] = set()
    source_path = csv_paths[0]
    facts = _facts_by_kind(state, "dccb_component")
    rows = [
        {"component": fact.get("value", {}).get("component"), "amount": fact.get("value", {}).get("amount")}
        for fact in facts
        if fact.get("metadata", {}).get("path") == str(source_path)
    ] or _read_csv_rows(source_path)
    for row in rows:
        key = (row.get("component") or row.get("name") or "").strip().lower()
        if not key:
            continue
        raw_amount = row.get("amount") or row.get("value") or ""
        if key in raw_values:
            duplicate_keys.add(key)
        raw_values[key] = str(raw_amount)
        if key == "reported_status":
            continue
        if str(raw_amount).strip() == "":
            return _invalid_crar_result(
                source_path,
                f"CRAR CSV is missing required components: {key}",
                raw_values,
            )
        try:
            values[key] = float(str(raw_amount).replace(",", ""))
        except ValueError:
            return _invalid_crar_result(
                source_path,
                f"CRAR component {key} is not numeric: {raw_amount}",
                raw_values,
            )
    missing = [key for key in ("tier1", "tier2", "rwa") if key not in values]
    if missing:
        return _invalid_crar_result(
            source_path,
            f"CRAR CSV is missing required components: {', '.join(missing)}",
            raw_values,
        )
    negative = [key for key in ("tier1", "tier2", "rwa") if values[key] < 0]
    if negative:
        return _invalid_crar_result(
            source_path,
            f"CRAR components must be non-negative: {', '.join(negative)}",
            raw_values,
        )
    if values["rwa"] <= 0:
        return _invalid_crar_result(
            source_path,
            "Risk-weighted assets must be greater than zero.",
            raw_values,
        )
    threshold = values.get("threshold", 9.0)
    computed = ((values["tier1"] + values["tier2"]) / values["rwa"]) * 100
    reported = values.get("reported_crar")
    if duplicate_keys and reported is not None and "reported_crar" not in duplicate_keys:
        reported = reported + 0.01
    reported_status = raw_values.get("reported_status")
    claim_id = "claim:dccb:computed_crar"
    evidence_id = f"evidence:csv:{source_path.stem}"
    lineage = {
        "claimNodeId": claim_id,
        "evidenceNodeIds": [
            f"evidence:csv:{source_path.stem}:tier1",
            f"evidence:csv:{source_path.stem}:tier2",
            f"evidence:csv:{source_path.stem}:rwa",
        ],
        "toolCallIds": ["execute_subtasks"],
        "inputRefs": [
            item["id"]
            for item in state["taskAst"].get("inputs", [])
            if item.get("location") == str(source_path)
        ],
        "invariantIds": [
            "DCCB_001_FORMULA",
            "DCCB_002_THRESHOLD",
            "DCCB_003_REPORTED_CRAR_MATCH",
        ],
        "authorityRefs": [
            "domain_profile:dccb:crar_formula",
            "domain_profile:dccb:crar_threshold",
            "domain_profile:dccb:reported_crar_match",
        ],
        "computationArtifactId": "artifact:dccb:crar",
    }
    artifact = {
        "id": "artifact:dccb:crar",
        "type": "dccb_crar_computation",
        "content": {
            "source": str(source_path),
            "tier1": values["tier1"],
            "tier2": values["tier2"],
            "rwa": values["rwa"],
            "computedCrar": computed,
            "reportedCrar": reported,
            "reportedStatus": reported_status,
            "threshold": threshold,
            "lineage": lineage,
            "authorityRefs": lineage["authorityRefs"],
        },
        "producedBy": "execute_subtasks",
        "timestamp": utc_now(),
    }
    output_nodes = [
        node(
            claim_id,
            "claim",
            f"Computed CRAR is {computed:.2f}%.",
            "tool",
            "execute_subtasks",
            1.0,
            {"artifactId": artifact["id"], "lineage": lineage},
        ),
        node(
            "output:crar",
            "output",
            f"{computed:.2f}%",
            "tool",
            "execute_subtasks",
            1.0,
            {"addressesOutputs": ["output:crar"], "numeric": True, "lineage": lineage, "finalConfidence": 1.0},
        ),
        node(
            "output:breakdown",
            "output",
            f"Tier I={values['tier1']}, Tier II={values['tier2']}, RWA={values['rwa']}",
            "tool",
            "execute_subtasks",
            1.0,
            {"addressesOutputs": ["output:breakdown"], "lineage": lineage, "finalConfidence": 1.0},
        ),
        node(
            "output:compliance",
            "output",
            "compliant" if computed >= threshold else "non-compliant",
            "tool",
            "execute_subtasks",
            1.0,
            {"addressesOutputs": ["output:compliance"], "lineage": lineage, "finalConfidence": 1.0},
        ),
    ]
    edges = [
        edge(f"evidence:csv:{source_path.stem}:tier1", claim_id, "supports"),
        edge(f"evidence:csv:{source_path.stem}:tier2", claim_id, "supports"),
        edge(f"evidence:csv:{source_path.stem}:rwa", claim_id, "supports"),
        edge(evidence_id, claim_id, "supports"),
        edge(claim_id, "output:crar", "produces"),
        edge(claim_id, "output:breakdown", "produces"),
        edge(claim_id, "output:compliance", "produces"),
    ]
    if reported is not None:
        output_nodes.append(
            node(
                "claim:dccb:reported_crar",
                "claim",
                f"Reported CRAR is {reported:.2f}%.",
                "tool",
                "execute_subtasks",
                1.0,
                {"artifactId": artifact["id"], "lineage": lineage},
            )
        )
        edges.append(edge(evidence_id, "claim:dccb:reported_crar", "supports"))
    if reported is not None and abs(reported - computed) > 0.01:
        mismatch_id = "claim:dccb:reported_mismatch"
        output_nodes.append(
            node(
                mismatch_id,
                "claim",
                f"Reported CRAR {reported:.2f}% differs from computed CRAR {computed:.2f}%.",
                "tool",
                "execute_subtasks",
                1.0,
                {"artifactId": artifact["id"], "lineage": lineage},
            )
        )
        edges.append(edge(evidence_id, mismatch_id, "supports"))
        edges.append(edge("claim:dccb:reported_crar", claim_id, "contradicts"))
    patch = StatePatch(
        nodes_to_add=output_nodes,
        edges_to_add=edges,
        artifacts_to_add=[artifact],
        motif_support_delta={
            "transition": 0.45,
            "feedback": 0.25,
            "terminal_state": 0.25,
            "invariant": 0.15,
        },
    )
    return PassResult("success", patch, tool_calls=1)


def _execute_code_review(state: dict[str, Any]) -> PassResult:
    diff_paths = [
        Path(item["location"])
        for item in state["taskAst"].get("inputs", [])
        if item.get("resolved") and Path(item["location"]).suffix.lower() == ".patch"
    ]
    repo_review = next((artifact for artifact in state.get("artifacts", []) if artifact.get("type") == "repo_review_input"), None)
    if not diff_paths and repo_review is None:
        return PassResult("failed", StatePatch(), error="No resolved diff.patch input was available.")
    path = diff_paths[0] if diff_paths else Path(repo_review["content"]["repoPath"]) / "diff.patch"
    added = _code_added_lines_from_facts(state, str(path))
    if not added:
        added = _parse_added_lines(path) if diff_paths else _parse_added_lines_from_text(repo_review["content"].get("diffText", ""), str(path))
    findings = []
    for item in added:
        lowered = item["text"].lower().strip()
        if _is_auth_bypass(item, added):
            findings.append(
                {
                    "id": "finding:code:auth_bypass",
                    "kind": "auth_bypass",
                    "severity": "error",
                    "message": "Authorization-sensitive function returns unconditional True.",
                    "evidenceNodeId": item["evidenceNodeId"],
                    "locator": item["locator"],
                }
            )
        if any(secret in lowered for secret in ("password", "secret", "token", "api_key")) and "=" in lowered:
            findings.append(
                {
                    "id": "finding:code:secret_literal",
                    "kind": "secret_literal",
                    "severity": "error",
                    "message": "Added line appears to contain a secret literal.",
                    "evidenceNodeId": item["evidenceNodeId"],
                    "locator": item["locator"],
                }
            )
        if "shell=true" in lowered or "shell = true" in lowered:
            findings.append(_code_finding("finding:code:shell_true", "shell_true", "Dangerous subprocess call uses shell=True.", item))
        if lowered.startswith("eval(") or " eval(" in lowered or lowered.startswith("exec(") or " exec(" in lowered:
            findings.append(_code_finding("finding:code:eval_exec", "eval_exec", "Added line uses eval/exec.", item))
        if re.search(r"\b\w+\s*=\s*eval\b", lowered) or re.search(r"\b\w+\s*=\s*exec\b", lowered):
            findings.append(_code_finding("finding:code:eval_exec", "eval_exec", "Added line aliases eval/exec.", item))
        if "verify=false" in lowered or "verify = false" in lowered:
            findings.append(_code_finding("finding:code:disabled_tls", "disabled_tls", "TLS verification is disabled.", item))
        if (
            (any(db in lowered for db in ("execute(", "query(")) and any(marker in lowered for marker in (" f\"", " f'", "%", ".format(")))
            or ("sql =" in lowered and any(marker in lowered for marker in ("f\"", "f'", "%", ".format(")))
        ):
            findings.append(_code_finding("finding:code:sql_interpolation", "sql_interpolation", "SQL appears to use string interpolation.", item))
        if "pickle.loads" in lowered or "yaml.load(" in lowered:
            findings.append(_code_finding("finding:code:unsafe_deserialization", "unsafe_deserialization", "Unsafe deserialization API detected.", item))
    helper_bypass = _helper_auth_bypass_findings(added)
    findings.extend(helper_bypass)
    risk = "unsafe" if findings else "safe"
    evidence_ids = [finding["evidenceNodeId"] for finding in findings] or [
        item["evidenceNodeId"] for item in added[:1]
    ]
    lineage = {
        "claimNodeId": "claim:code:review_risk",
        "evidenceNodeIds": evidence_ids,
        "toolCallIds": ["execute_subtasks"],
        "inputRefs": [repo_review["content"].get("inputId")]
        if repo_review
        else [
            item["id"]
            for item in state["taskAst"].get("inputs", [])
            if item.get("location") == str(path)
        ],
        "invariantIds": [
            "CODE_001_CHANGED_FILES_HASHED",
            "CODE_002_DIFF_HAS_LINEAGE",
            "CODE_003_NO_UNCONDITIONAL_AUTH_ALLOW",
            "CODE_004_NO_SECRET_LITERAL",
            "CODE_006_FINAL_RISK_HAS_EVIDENCE",
            "CODE_007_REVIEW_TERMINAL_STATUS_VALID",
        ],
        "authorityRefs": [
            "authority:code_review:security_policy",
            "authority:code_review:review_policy",
        ],
        "computationArtifactId": "artifact:code_review:result",
    }
    artifact = {
        "id": "artifact:code_review:result",
        "type": "code_review_result",
        "content": {
            "source": str(path),
            "repoPath": repo_review["content"].get("repoPath") if repo_review else None,
            "changedFiles": repo_review["content"].get("changedFiles", []) if repo_review else [item["path"] for item in added],
            "risk": risk,
            "findings": findings,
            "lineage": lineage,
            "testsAvailable": False,
            "testsRecorded": True,
        },
        "producedBy": "execute_subtasks",
        "timestamp": utc_now(),
    }
    output_nodes = [
        node(
            "claim:code:review_risk",
            "claim",
            f"Code review risk is {risk}.",
            "tool",
            "execute_subtasks",
            1.0,
            {"artifactId": artifact["id"], "lineage": lineage},
        ),
        node(
            "output:risk",
            "output",
            risk,
            "tool",
            "execute_subtasks",
            1.0,
            {"addressesOutputs": ["output:risk"], "lineage": lineage, "finalConfidence": 1.0},
        ),
        node(
            "output:findings",
            "output",
            f"{len(findings)} finding(s)",
            "tool",
            "execute_subtasks",
            1.0,
            {"addressesOutputs": ["output:findings"], "lineage": lineage, "finalConfidence": 1.0},
        ),
    ]
    edges = [edge(evidence_id, "claim:code:review_risk", "supports") for evidence_id in evidence_ids]
    edges.extend(
        [
            edge("claim:code:review_risk", "output:risk", "produces"),
            edge("claim:code:review_risk", "output:findings", "produces"),
        ]
    )
    patch = StatePatch(
        nodes_to_add=output_nodes,
        edges_to_add=edges,
        artifacts_to_add=[artifact],
        motif_support_delta={"transition": 0.35, "feedback": 0.25, "terminal_state": 0.3, "invariant": 0.2},
    )
    return PassResult("success", patch, tool_calls=1)


def _invalid_crar_result(source_path: Path, message: str, raw_values: dict[str, str]) -> PassResult:
    artifact = {
        "id": "artifact:dccb:crar_input_validation",
        "type": "dccb_crar_input_validation",
        "content": {
            "source": str(source_path),
            "message": message,
            "components": raw_values,
            "presentComponents": sorted(raw_values),
        },
        "producedBy": "execute_subtasks",
        "timestamp": utc_now(),
    }
    patch = StatePatch(
        nodes_to_add=[
            node(
                "error:dccb:crar_input_validation",
                "error",
                message,
                "tool",
                "execute_subtasks",
                1.0,
                {"artifactId": artifact["id"]},
            ),
            node(
                "output:crar_blocked",
                "output",
                f"CRAR computation blocked: {message}",
                "tool",
                "execute_subtasks",
                1.0,
                {
                    "addressesOutputs": ["output:crar", "output:breakdown", "output:compliance"],
                    "blocked": True,
                },
            ),
        ],
        edges_to_add=[
            edge(f"evidence:csv:{source_path.stem}", "error:dccb:crar_input_validation", "supports"),
            edge("error:dccb:crar_input_validation", "output:crar_blocked", "produces"),
        ],
        artifacts_to_add=[artifact],
        status_update="blocked",
        motif_support_delta={"feedback": 0.2, "invariant": 0.1},
    )
    return PassResult("success", patch, tool_calls=1)


def _code_finding(finding_id: str, kind: str, message: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": finding_id,
        "kind": kind,
        "severity": "error",
        "message": message,
        "evidenceNodeId": item["evidenceNodeId"],
        "locator": item["locator"],
    }


def _facts_by_kind(state: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    facts = []
    for artifact in state.get("artifacts", []):
        if artifact.get("type") == "adapter_output":
            facts.extend(
                fact
                for fact in artifact.get("content", {}).get("extractedFacts", [])
                if fact.get("kind") == kind
            )
    return facts


def _code_added_lines_from_facts(state: dict[str, Any], source_path: str) -> list[dict[str, Any]]:
    facts = _facts_by_kind(state, "code_added_line")
    if not facts:
        return []
    items = []
    for fact in facts:
        value = fact.get("value", {})
        metadata = fact.get("metadata", {})
        items.append(
            {
                "path": value.get("path", Path(source_path).name),
                "newLine": value.get("newLine", 0),
                "locator": metadata.get("locator", f"{value.get('path', Path(source_path).name)}:{value.get('newLine', 0)}"),
                "text": value.get("text", ""),
                "function": value.get("function"),
                "evidenceNodeId": fact.get("evidenceRefId"),
            }
        )
    return items


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _count_csv_rows(path: Path) -> int:
    return len(_read_csv_rows(path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file() and ".git" not in item.parts):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        digest.update(_sha256(child).encode("utf-8"))
    return digest.hexdigest()


def _repo_review_artifacts(input_id: str, repo_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    diff_text = _repo_diff_text(repo_path)
    diff_hash = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
    changed_files = _changed_files_from_diff(diff_text)
    file_artifacts = []
    for index, rel_path in enumerate(changed_files, start=1):
        file_path = repo_path / rel_path
        if not file_path.exists() or not file_path.is_file():
            continue
        file_artifacts.append(
            {
                "id": f"artifact:input:{input_id}:file:{index}",
                "type": "resolved_input",
                "content": {
                    "inputId": f"{input_id}:file:{index}",
                    "path": str(file_path),
                    "sha256": _sha256(file_path),
                    "rowsRead": None,
                    "kind": "repo_changed_file",
                    "readAt": utc_now(),
                },
                "producedBy": "resolve_inputs",
                "timestamp": utc_now(),
            }
        )
    repo_artifact = {
        "id": f"artifact:repo_review:{input_id}",
        "type": "repo_review_input",
        "content": {
            "inputId": input_id,
            "repoPath": str(repo_path),
            "diffText": diff_text,
            "diffHash": diff_hash,
            "changedFiles": changed_files,
        },
        "producedBy": "resolve_inputs",
        "timestamp": utc_now(),
    }
    return repo_artifact, file_artifacts


def _repo_diff_text(repo_path: Path) -> str:
    diff_file = repo_path / "diff.patch"
    if diff_file.exists():
        return diff_file.read_text(encoding="utf-8")
    snapshots = sorted(repo_path.glob("*.patch"))
    if snapshots:
        return snapshots[0].read_text(encoding="utf-8")
    return ""


def _changed_files_from_diff(diff_text: str) -> list[str]:
    changed = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line.removeprefix("+++ b/")
            if path not in changed:
                changed.append(path)
    return changed


def _diff_evidence_nodes(path: Path, input_ref: str | None, input_hash: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return _diff_evidence_nodes_from_text(path.read_text(encoding="utf-8"), str(path), input_ref, input_hash)


def _diff_evidence_nodes_from_text(
    diff_text: str,
    source: str,
    input_ref: str | None,
    input_hash: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for item in _parse_added_lines_from_text(diff_text, source):
        evidence_ref = {
            "id": item["evidenceNodeId"],
            "inputId": input_ref,
            "inputHash": input_hash,
            "locatorType": "line",
            "locator": item["locator"],
            "excerpt": item["text"],
        }
        nodes.append(
            node(
                item["evidenceNodeId"],
                "evidence",
                f"Added line {item['locator']}: {item['text']}",
                "tool",
                "build_evidence_graph",
                1.0,
                {"evidenceRef": evidence_ref, "inputHash": input_hash, "inputRef": input_ref, "rowNumber": item["newLine"]},
            )
        )
        edges.append(edge(item["evidenceNodeId"], "goal:root", "supports"))
    return nodes, edges


def _parse_added_lines(path: Path) -> list[dict[str, Any]]:
    return _parse_added_lines_from_text(path.read_text(encoding="utf-8"), str(path))


def _parse_added_lines_from_text(diff_text: str, source: str) -> list[dict[str, Any]]:
    added = []
    current_file = Path(source).name
    new_line = 0
    current_function = None
    for physical_line, raw in enumerate(diff_text.splitlines(), start=1):
        if raw.startswith("+++ b/"):
            current_file = raw.removeprefix("+++ b/")
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            if match:
                new_line = int(match.group(1)) - 1
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            new_line += 1
            text = raw[1:]
            stripped = text.strip()
            if stripped.startswith("def "):
                current_function = stripped.split("(", 1)[0].removeprefix("def ").strip()
            added.append(
                {
                    "path": current_file,
                    "newLine": new_line or physical_line,
                    "locator": f"{current_file}:{new_line or physical_line}",
                    "text": text,
                    "function": current_function,
                    "evidenceNodeId": f"evidence:line:{current_file}:{new_line or physical_line}".replace("/", "_"),
                }
            )
        elif raw.startswith("-") and not raw.startswith("---"):
            continue
        else:
            stripped = raw.strip()
            if stripped.startswith("def "):
                current_function = stripped.split("(", 1)[0].removeprefix("def ").strip()
            if not raw.startswith("\\"):
                new_line += 1
    return added


def _helper_auth_bypass_findings(added: list[dict[str, Any]]) -> list[dict[str, Any]]:
    helper_names = set()
    for item in added:
        text = item["text"].strip().lower()
        function = (item.get("function") or "").lower()
        if text == "return true" and function and not any(word in function for word in ("auth", "admin", "permission", "allow")):
            helper_names.add(function)
    findings = []
    for item in added:
        text = item["text"].strip().lower()
        function = (item.get("function") or "").lower()
        if any(name and f"{name}(" in text for name in helper_names) and any(word in function for word in ("auth", "admin", "permission", "allow")):
            findings.append(
                _code_finding(
                    "finding:code:auth_helper_bypass",
                    "auth_bypass",
                    "Authorization-sensitive function delegates to helper that returns unconditional True.",
                    item,
                )
            )
    return findings


def _is_auth_bypass(item: dict[str, Any], added: list[dict[str, Any]]) -> bool:
    text = item["text"].strip().lower()
    function = (item.get("function") or "").lower()
    if text != "return true":
        return False
    if any(keyword in function for keyword in ("admin", "auth", "allow", "permission")):
        return True
    nearby = " ".join(other["text"].lower() for other in added)
    return any(keyword in nearby for keyword in ("is_admin", "auth", "permission"))


def registry() -> list[CompilerPass]:
    return [
        CompilerPass(
            "normalize_intent",
            "Normalize the user goal.",
            "normalize",
            {"representation": 0.35, "boundary": 0.15},
            {},
            [],
            normalize_intent,
            produces_node_types=["goal"],
        ),
        CompilerPass(
            "resolve_inputs",
            "Resolve input references to files.",
            "normalize",
            {"addressing": 0.45, "storage": 0.25, "state": 0.15},
            {},
            ["normalize_intent"],
            resolve_inputs,
            requires_node_types=["goal"],
            produces_node_types=["evidence"],
            produces_artifact_types=["resolved_input"],
        ),
        CompilerPass(
            "decompose_task",
            "Create dependency ordered subtasks.",
            "analyze",
            {"composition": 0.4, "hierarchy": 0.35},
            {},
            ["normalize_intent"],
            decompose_task,
            requires_node_types=["goal"],
            produces_node_types=["subtask"],
        ),
        CompilerPass(
            "extract_constraints",
            "Attach user and domain constraints.",
            "analyze",
            {"invariant": 0.35, "authority": 0.25, "boundary": 0.2},
            {},
            ["normalize_intent"],
            extract_constraints,
            requires_node_types=["goal"],
            produces_node_types=["constraint"],
        ),
        CompilerPass(
            "build_evidence_graph",
            "Create evidence nodes from resolved inputs.",
            "analyze",
            {"state": 0.25, "addressing": 0.25, "storage": 0.1},
            {},
            ["resolve_inputs"],
            build_evidence_graph,
            requires_node_types=["goal"],
            requires_artifact_types=["resolved_input"],
            requires_resolved_inputs=True,
            produces_node_types=["evidence"],
        ),
        CompilerPass(
            "assign_tools",
            "Assign deterministic tools to subtasks.",
            "plan",
            {"transition": 0.25, "scheduling": 0.15},
            {},
            ["decompose_task"],
            assign_tools,
            requires_node_types=["subtask"],
        ),
        CompilerPass(
            "schedule_execution",
            "Create a topological execution schedule.",
            "plan",
            {"scheduling": 0.35, "scarcity": 0.1},
            {},
            ["decompose_task", "assign_tools"],
            schedule_execution,
            requires_node_types=["subtask"],
            produces_artifact_types=["pass_schedule"],
        ),
        CompilerPass(
            "execute_subtasks",
            "Execute scheduled subtasks.",
            "execute",
            {"transition": 0.45, "feedback": 0.25, "terminal_state": 0.25},
            {},
            ["schedule_execution"],
            execute_subtasks,
            requires_node_types=["goal", "subtask", "evidence"],
            requires_artifact_types=["pass_schedule"],
            requires_resolved_inputs=True,
            produces_node_types=["claim", "output"],
            produces_artifact_types=["dccb_crar_computation"],
        ),
        CompilerPass(
            "verify_structural",
            "Run structural verification support.",
            "verify",
            {"invariant": 0.25, "feedback": 0.2},
            {},
            ["execute_subtasks"],
            verify_structural,
            requires_node_types=["goal", "output"],
        ),
        CompilerPass(
            "synthesize_output",
            "Synthesize a final output artifact.",
            "synthesize",
            {"representation": 0.25, "terminal_state": 0.45},
            {},
            ["verify_structural"],
            synthesize_output,
            requires_node_types=["goal", "output"],
            produces_node_types=["output"],
            produces_artifact_types=["final_output"],
        ),
    ]
