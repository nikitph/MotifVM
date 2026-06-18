from __future__ import annotations

from typing import Any


def result(
    invariant_id: str,
    passed: bool,
    severity: str,
    message: str,
    evidence: list[str] | None = None,
    suggested_fix: str | None = None,
) -> dict[str, Any]:
    data = {
        "invariantId": invariant_id,
        "passed": passed,
        "severity": severity,
        "message": message,
        "evidence": evidence or [],
        "autoFixable": suggested_fix is not None,
        "suggestedFix": suggested_fix,
    }
    authority_refs = _authority_refs_for_invariant(invariant_id)
    if authority_refs:
        data["authorityRefs"] = authority_refs
    return data


def _authority_refs_for_invariant(invariant_id: str) -> list[str]:
    mapping = {
        "DCCB_001_FORMULA": ["domain_profile:dccb:crar_formula"],
        "DCCB_002_THRESHOLD": ["domain_profile:dccb:crar_threshold"],
        "DCCB_003_REPORTED_CRAR_MATCH": ["domain_profile:dccb:reported_crar_match"],
        "DCCB_004_CAPITAL_COMPONENTS_PRESENT": ["domain_profile:dccb:crar_formula"],
        "DCCB_005_NUMERIC_FIELDS_VALID": ["domain_profile:dccb:crar_formula"],
        "DCCB_006_RWA_POSITIVE": ["domain_profile:dccb:crar_formula"],
        "DCCB_007_THRESHOLD_CLASSIFICATION": ["domain_profile:dccb:crar_threshold"],
        "DCCB_008_REPORTED_STATUS_MATCH": ["domain_profile:dccb:crar_threshold"],
        "CODE_001_CHANGED_FILES_HASHED": ["authority:code_review:review_policy"],
        "CODE_002_DIFF_HAS_LINEAGE": ["authority:code_review:review_policy"],
        "CODE_003_NO_UNCONDITIONAL_AUTH_ALLOW": ["authority:code_review:security_policy"],
        "CODE_004_NO_SECRET_LITERAL": ["authority:code_review:security_policy"],
        "CODE_005_TEST_STATUS_RECORDED": ["authority:code_review:test_policy"],
        "CODE_006_FINAL_RISK_HAS_EVIDENCE": ["authority:code_review:review_policy"],
        "CODE_007_REVIEW_TERMINAL_STATUS_VALID": ["authority:code_review:review_policy"],
    }
    return mapping.get(invariant_id, [])


def check_edge_endpoints(state: dict[str, Any]) -> dict[str, Any]:
    nodes = state.get("graph", {}).get("nodes", {})
    missing: list[str] = []
    for edge in state.get("graph", {}).get("edges", []):
        if edge.get("from") not in nodes:
            missing.append(edge.get("from", "<missing-from>"))
        if edge.get("to") not in nodes:
            missing.append(edge.get("to", "<missing-to>"))
    return result(
        "STRUCT_006",
        not missing,
        "error",
        "Every edge endpoint references an existing node."
        if not missing
        else f"Missing edge endpoints: {', '.join(sorted(set(missing)))}",
        sorted(set(missing)),
    )


def check_graph_duplicate_edges(state: dict[str, Any]) -> dict[str, Any]:
    seen = set()
    duplicates = []
    for edge in state.get("graph", {}).get("edges", []):
        key = (edge.get("from"), edge.get("to"), edge.get("relation"))
        if key in seen:
            duplicates.append("->".join(str(part) for part in key))
        seen.add(key)
    return result(
        "GRAPH_002",
        not duplicates,
        "error",
        "No duplicate graph edges exist."
        if not duplicates
        else f"Duplicate edges: {', '.join(duplicates)}",
        duplicates,
    )


def check_final_output_lineage_to_goal(state: dict[str, Any]) -> dict[str, Any]:
    edges = state.get("graph", {}).get("edges", [])
    reaches_goal = any(edge.get("from") == "goal:root" and edge.get("to") == "output:final" for edge in edges)
    return result(
        "GRAPH_004",
        reaches_goal or "output:final" not in state.get("graph", {}).get("nodes", {}),
        "error",
        "Every final output has lineage to the root goal."
        if reaches_goal or "output:final" not in state.get("graph", {}).get("nodes", {})
        else "Final output is not linked to root goal.",
        ["output:final"] if not reaches_goal and "output:final" in state.get("graph", {}).get("nodes", {}) else [],
    )


def check_evidence_nodes_have_evidence_ref(state: dict[str, Any]) -> dict[str, Any]:
    missing = []
    for node_id, node in state.get("graph", {}).get("nodes", {}).items():
        if node.get("type") != "evidence":
            continue
        meta = node.get("meta", {})
        if "component" in meta or node_id.startswith("evidence:line:"):
            if not meta.get("evidenceRef"):
                missing.append(node_id)
    return result(
        "GRAPH_005",
        not missing,
        "error",
        "Every evidence node has EvidenceRef metadata."
        if not missing
        else f"Evidence nodes missing EvidenceRef: {', '.join(missing)}",
        missing,
    )


def check_rejected_claim_reason(state: dict[str, Any]) -> dict[str, Any]:
    missing = [
        node_id
        for node_id, node in state.get("graph", {}).get("nodes", {}).items()
        if node.get("type") == "claim"
        and node.get("status") == "rejected"
        and not node.get("meta", {}).get("rejectionReason")
    ]
    return result(
        "GRAPH_007",
        not missing,
        "error",
        "Every rejected claim has a rejection reason."
        if not missing
        else f"Rejected claims missing reasons: {', '.join(missing)}",
        missing,
    )


def check_final_claim_confidence(state: dict[str, Any]) -> dict[str, Any]:
    missing = []
    for node_id, node in state.get("graph", {}).get("nodes", {}).items():
        if node.get("type") == "output" and node.get("meta", {}).get("lineage"):
            if "finalConfidence" not in node.get("meta", {}):
                missing.append(node_id)
    return result(
        "CONF_001",
        not missing,
        "error",
        "Final claims include confidence."
        if not missing
        else f"Final claims missing confidence: {', '.join(missing)}",
        missing,
    )


def check_final_confidence_weakest_link(state: dict[str, Any]) -> dict[str, Any]:
    nodes = state.get("graph", {}).get("nodes", {})
    bad = []
    for node_id, node in nodes.items():
        lineage = node.get("meta", {}).get("lineage")
        if node.get("type") != "output" or not lineage or "finalConfidence" not in node.get("meta", {}):
            continue
        deps = [lineage.get("claimNodeId"), *lineage.get("evidenceNodeIds", [])]
        confidences = [float(nodes[dep].get("confidence", 1.0)) for dep in deps if dep in nodes]
        if confidences and float(node["meta"]["finalConfidence"]) > min(confidences):
            bad.append(node_id)
    return result(
        "CONF_002",
        not bad,
        "error",
        "Final confidence is no greater than weakest required dependency."
        if not bad
        else f"Final confidence exceeds dependency confidence: {', '.join(bad)}",
        bad,
    )


def check_root_goal_exists(state: dict[str, Any]) -> dict[str, Any]:
    nodes = state.get("graph", {}).get("nodes", {})
    goal = nodes.get("goal:root")
    return result(
        "STRUCT_GOAL_001",
        bool(goal and goal.get("type") == "goal"),
        "error",
        "Root goal node exists before graph attachments."
        if goal and goal.get("type") == "goal"
        else "Root goal node is missing.",
        ["goal:root"] if goal else [],
    )


def check_confidence_range(state: dict[str, Any]) -> dict[str, Any]:
    bad = [
        node_id
        for node_id, node in state.get("graph", {}).get("nodes", {}).items()
        if not 0.0 <= float(node.get("confidence", -1.0)) <= 1.0
    ]
    return result(
        "TYPE_001",
        not bad,
        "error",
        "All confidence scores are in [0.0, 1.0]."
        if not bad
        else f"Nodes with invalid confidence: {', '.join(bad)}",
        bad,
    )


def check_no_unresolved_contradictions(state: dict[str, Any]) -> dict[str, Any]:
    contradictions = [
        edge
        for edge in state.get("graph", {}).get("edges", [])
        if edge.get("relation") == "contradicts"
    ]
    return result(
        "COHER_002",
        not contradictions,
        "warning",
        "No unresolved contradiction edges in final graph."
        if not contradictions
        else "Contradiction edges remain and should be reviewed.",
    )


def check_claim_support(state: dict[str, Any]) -> dict[str, Any]:
    nodes = state.get("graph", {}).get("nodes", {})
    supported = {
        edge.get("to")
        for edge in state.get("graph", {}).get("edges", [])
        if edge.get("relation") == "supports"
    }
    unsupported = [
        node_id
        for node_id, node in nodes.items()
        if node.get("type") == "claim"
        and node.get("source") == "llm"
        and node_id not in supported
        and not node.get("meta", {}).get("markedAssumption")
    ]
    return result(
        "TRACE_003",
        not unsupported,
        "warning",
        "Every LLM-created factual claim has evidence or is marked as assumption."
        if not unsupported
        else f"Unsupported factual claims: {', '.join(unsupported)}",
        unsupported,
        "Add evidence edges or mark unsupported claims as assumptions.",
    )


def check_required_outputs(state: dict[str, Any]) -> dict[str, Any]:
    required = [
        output["id"]
        for output in state.get("taskAst", {}).get("requiredOutputs", [])
        if output.get("required", True)
    ]
    addressed = set()
    for node in state.get("graph", {}).get("nodes", {}).values():
        if node.get("type") == "output":
            addressed.update(node.get("meta", {}).get("addressesOutputs", []))
    missing = [output_id for output_id in required if output_id not in addressed]
    return result(
        "TERM_001",
        not missing,
        "error",
        "All required outputs have output nodes."
        if not missing
        else f"Missing required output nodes: {', '.join(missing)}",
        missing,
    )


def check_final_output_lineage(state: dict[str, Any]) -> dict[str, Any]:
    nodes = state.get("graph", {}).get("nodes", {})
    missing = []
    for node_id, node in nodes.items():
        if node.get("type") != "output":
            continue
        if "final" not in node_id and node_id != "output:crar":
            continue
        lineage = node.get("meta", {}).get("lineage", {})
        if not lineage.get("evidenceNodeIds") and node_id != "output:summary":
            missing.append(node_id)
    return result(
        "TRACE_001",
        not missing,
        "error",
        "Every final output claim traces to evidence or a tool result."
        if not missing
        else f"Output nodes missing lineage: {', '.join(missing)}",
        missing,
    )


def check_numeric_output_trace(state: dict[str, Any]) -> dict[str, Any]:
    nodes = state.get("graph", {}).get("nodes", {})
    missing = []
    for node_id, node in nodes.items():
        if node.get("type") != "output" or not node.get("meta", {}).get("numeric"):
            continue
        lineage = node.get("meta", {}).get("lineage", {})
        if not lineage.get("computationArtifactId") or len(lineage.get("evidenceNodeIds", [])) == 0:
            missing.append(node_id)
    return result(
        "TRACE_002",
        not missing,
        "error",
        "Every numeric output traces to source inputs and a computation artifact."
        if not missing
        else f"Numeric outputs missing computation trace: {', '.join(missing)}",
        missing,
    )


def check_domain_invariants_have_authority(state: dict[str, Any]) -> dict[str, Any]:
    domain = state.get("taskAst", {}).get("meta", {}).get("domain")
    if domain not in {"dccb_audit", "code_review"}:
        return result("AUTH_001", True, "info", "No domain invariants required authority refs.")
    authorities = {item.get("id") for item in state.get("authorityRefs", [])}
    if domain == "dccb_audit":
        required = {
            "domain_profile:dccb:crar_formula",
            "domain_profile:dccb:crar_threshold",
            "domain_profile:dccb:reported_crar_match",
        }
    else:
        required = {
            "authority:code_review:security_policy",
            "authority:code_review:review_policy",
            "authority:code_review:test_policy",
        }
    missing = sorted(required - authorities)
    return result(
        "AUTH_001",
        not missing,
        "error",
        "Every domain invariant references an AuthorityRef."
        if not missing
        else f"Missing domain authority refs: {', '.join(missing)}",
        missing,
    )


def check_authority_sensitive_outputs(state: dict[str, Any]) -> dict[str, Any]:
    missing = []
    for node_id, node in state.get("graph", {}).get("nodes", {}).items():
        if node.get("type") != "output":
            continue
        lineage = node.get("meta", {}).get("lineage", {})
        if lineage and not lineage.get("authorityRefs"):
            missing.append(node_id)
    return result(
        "AUTH_002",
        not missing,
        "error",
        "Every authority-sensitive output claim traces to at least one AuthorityRef."
        if not missing
        else f"Authority-sensitive outputs missing AuthorityRefs: {', '.join(missing)}",
        missing,
    )


def check_resolved_inputs_have_hash(state: dict[str, Any]) -> dict[str, Any]:
    missing = [
        item.get("inputId") or item.get("path", "<unknown>")
        for item in state.get("inputManifest", [])
        if not item.get("sha256")
    ]
    return result(
        "INPUT_001",
        not missing,
        "error",
        "Every resolved input has a content hash."
        if not missing
        else f"Resolved inputs missing hashes: {', '.join(missing)}",
        missing,
    )


def check_evidence_rows_reference_hash(state: dict[str, Any]) -> dict[str, Any]:
    missing = []
    for node_id, node in state.get("graph", {}).get("nodes", {}).items():
        if node.get("type") != "evidence":
            continue
        meta = node.get("meta", {})
        evidence_ref = meta.get("evidenceRef")
        if evidence_ref and (not evidence_ref.get("inputHash") or not evidence_ref.get("locator")):
            missing.append(node_id)
        elif "rowNumber" in meta and (not meta.get("inputHash") or not meta.get("rowNumber")):
            missing.append(node_id)
    return result(
        "INPUT_002",
        not missing,
        "error",
        "Every evidence row references an input hash and row number."
        if not missing
        else f"Evidence rows missing hash or row number: {', '.join(missing)}",
        missing,
    )


def check_code_changed_files_hashed(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "code_review":
        return None
    missing = [
        item.get("inputId") or item.get("path", "<unknown>")
        for item in state.get("inputManifest", [])
        if str(item.get("path", "")).endswith(".patch") and not item.get("sha256")
    ]
    return result(
        "CODE_001_CHANGED_FILES_HASHED",
        not missing,
        "error",
        "Every reviewed file/diff has an input hash."
        if not missing
        else f"Reviewed inputs missing hashes: {', '.join(missing)}",
        missing,
    )


def check_code_diff_has_lineage(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "code_review":
        return None
    missing = []
    for node_id, node in state.get("graph", {}).get("nodes", {}).items():
        if node.get("type") == "evidence" and node_id.startswith("evidence:line:"):
            ref = node.get("meta", {}).get("evidenceRef", {})
            if ref.get("locatorType") != "line" or not ref.get("locator"):
                missing.append(node_id)
    return result(
        "CODE_002_DIFF_HAS_LINEAGE",
        not missing,
        "error",
        "Every review claim can trace to file path and line number."
        if not missing
        else f"Line evidence missing locator: {', '.join(missing)}",
        missing,
    )


def check_code_no_unconditional_auth_allow(state: dict[str, Any]) -> dict[str, Any] | None:
    review = _code_review_artifact(state)
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "code_review":
        return None
    findings = review.get("content", {}).get("findings", []) if review else []
    bad = [finding["evidenceNodeId"] for finding in findings if finding.get("kind") == "auth_bypass"]
    return result(
        "CODE_003_NO_UNCONDITIONAL_AUTH_ALLOW",
        not bad,
        "error",
        "Authorization-sensitive functions do not return unconditional true."
        if not bad
        else "Authorization-sensitive function returns unconditional true.",
        bad,
    )


def check_code_no_secret_literal(state: dict[str, Any]) -> dict[str, Any] | None:
    review = _code_review_artifact(state)
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "code_review":
        return None
    findings = review.get("content", {}).get("findings", []) if review else []
    bad = [finding["evidenceNodeId"] for finding in findings if finding.get("kind") == "secret_literal"]
    return result(
        "CODE_004_NO_SECRET_LITERAL",
        not bad,
        "error",
        "Added lines do not contain obvious secrets/tokens/passwords."
        if not bad
        else "Added line appears to contain a secret literal.",
        bad,
    )


def check_code_test_status_recorded(state: dict[str, Any]) -> dict[str, Any] | None:
    review = _code_review_artifact(state)
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "code_review":
        return None
    recorded = bool(review and "testsRecorded" in review.get("content", {}))
    return result(
        "CODE_005_TEST_STATUS_RECORDED",
        recorded,
        "error",
        "Test status is recorded for code review."
        if recorded
        else "Test status artifact is missing.",
        [review["id"]] if review else [],
    )


def check_code_final_risk_has_evidence(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "code_review":
        return None
    node = state.get("graph", {}).get("nodes", {}).get("claim:code:review_risk")
    lineage = node.get("meta", {}).get("lineage", {}) if node else {}
    passed = bool(lineage.get("evidenceNodeIds"))
    return result(
        "CODE_006_FINAL_RISK_HAS_EVIDENCE",
        passed,
        "error",
        "Every final risk claim has evidence."
        if passed
        else "Final risk claim is missing evidence.",
        lineage.get("evidenceNodeIds", []),
    )


def check_code_review_terminal_status_valid(state: dict[str, Any]) -> dict[str, Any] | None:
    review = _code_review_artifact(state)
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "code_review":
        return None
    risk = review.get("content", {}).get("risk") if review else None
    findings = review.get("content", {}).get("findings", []) if review else []
    passed = (risk == "safe" and not findings) or (risk == "unsafe" and bool(findings))
    return result(
        "CODE_007_REVIEW_TERMINAL_STATUS_VALID",
        passed,
        "error",
        "Review terminal classification matches findings."
        if passed
        else "Review terminal classification does not match findings.",
        [review["id"]] if review else [],
    )


def check_reconciliation_does_not_mutate_source(state: dict[str, Any]) -> dict[str, Any]:
    bad = []
    for artifact in state.get("artifacts", []):
        if artifact.get("type") != "reconciliation_patch":
            continue
        content = artifact.get("content", {})
        if content.get("sourceMutated") is not False:
            bad.append(artifact.get("id"))
    return result(
        "RECON_001",
        not bad,
        "error",
        "Reconciliation patches do not mutate source input artifacts."
        if not bad
        else f"Reconciliation patches missing sourceMutated=false: {', '.join(bad)}",
        bad,
    )


def check_reconciliation_requires_confirmation(state: dict[str, Any]) -> dict[str, Any]:
    bad = []
    for artifact in state.get("artifacts", []):
        if artifact.get("type") != "reconciliation_patch":
            continue
        content = artifact.get("content", {})
        if content.get("requiresConfirmation") is not True:
            bad.append(artifact.get("id"))
    return result(
        "RECON_002",
        not bad,
        "error",
        "Audit-sensitive reconciliation patches include a human confirmation caveat."
        if not bad
        else f"Reconciliation patches missing confirmation caveat: {', '.join(bad)}",
        bad,
    )


def check_dccb_crar_formula(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "dccb_audit":
        return None
    crar = next(
        (
            artifact
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "dccb_crar_computation"
        ),
        None,
    )
    if crar is None:
        return result(
            "DCCB_001_FORMULA",
            False,
            "warning",
            "No CRAR computation artifact was produced.",
            suggested_fix="Provide a CSV with tier1, tier2, and rwa rows.",
        )
    content = crar.get("content", {})
    expected = round(
        ((float(content["tier1"]) + float(content["tier2"])) / float(content["rwa"])) * 100,
        6,
    )
    observed = round(float(content["computedCrar"]), 6)
    return result(
        "DCCB_001_FORMULA",
        expected == observed,
        "error",
        "CRAR formula matches (Tier I + Tier II) / RWA * 100."
        if expected == observed
        else f"CRAR formula mismatch: expected {expected}, observed {observed}.",
        [crar["id"]],
    )


def check_dccb_crar_threshold(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "dccb_audit":
        return None
    crar = next(
        (
            artifact
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "dccb_crar_computation"
        ),
        None,
    )
    if crar is None:
        return result(
            "DCCB_002_THRESHOLD",
            False,
            "warning",
            "CRAR threshold could not be checked because no computation exists.",
        )
    computed = float(crar.get("content", {}).get("computedCrar", 0.0))
    threshold = float(crar.get("content", {}).get("threshold", 9.0))
    return result(
        "DCCB_002_THRESHOLD",
        computed >= threshold,
        "error",
        f"Computed CRAR {computed:.2f}% meets the {threshold:.2f}% threshold."
        if computed >= threshold
        else f"Computed CRAR {computed:.2f}% is below the {threshold:.2f}% threshold.",
        [crar["id"]],
    )


def check_dccb_capital_components_present(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "dccb_audit":
        return None
    crar = _crar_artifact(state)
    if crar is not None:
        content = crar.get("content", {})
        missing = [key for key in ("tier1", "tier2", "rwa") if key not in content]
        return result(
            "DCCB_004_CAPITAL_COMPONENTS_PRESENT",
            not missing,
            "error",
            "Tier I, Tier II, and RWA are present before CRAR computation."
            if not missing
            else f"Missing CRAR components: {', '.join(missing)}",
            [crar["id"]],
        )
    validation = _crar_validation_artifact(state)
    if validation is not None:
        present = set(validation.get("content", {}).get("presentComponents", []))
        missing = [key for key in ("tier1", "tier2", "rwa") if key not in present]
        return result(
            "DCCB_004_CAPITAL_COMPONENTS_PRESENT",
            not missing,
            "error",
            "Tier I, Tier II, and RWA are present before CRAR computation."
            if not missing
            else f"Missing CRAR components: {', '.join(missing)}",
            [validation["id"]],
        )
    return result(
        "DCCB_004_CAPITAL_COMPONENTS_PRESENT",
        False,
        "warning",
        "No CRAR input validation or computation artifact exists yet.",
    )


def check_dccb_numeric_fields_valid(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "dccb_audit":
        return None
    crar = _crar_artifact(state)
    if crar is not None:
        content = crar.get("content", {})
        invalid = [
            key
            for key in ("tier1", "tier2", "rwa")
            if not isinstance(content.get(key), (int, float)) or float(content.get(key)) < 0
        ]
        return result(
            "DCCB_005_NUMERIC_FIELDS_VALID",
            not invalid,
            "error",
            "CRAR inputs are numeric, non-null, and non-negative."
            if not invalid
            else f"Invalid CRAR numeric fields: {', '.join(invalid)}",
            [crar["id"]],
        )
    validation = _crar_validation_artifact(state)
    if validation is not None:
        message = validation.get("content", {}).get("message", "")
        failed = "not numeric" in message or "non-negative" in message
        return result(
            "DCCB_005_NUMERIC_FIELDS_VALID",
            not failed,
            "error",
            "CRAR inputs are numeric, non-null, and non-negative."
            if not failed
            else message,
            [validation["id"]],
        )
    return None


def check_dccb_rwa_positive(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "dccb_audit":
        return None
    crar = _crar_artifact(state)
    if crar is not None:
        rwa = float(crar.get("content", {}).get("rwa", 0.0))
        return result(
            "DCCB_006_RWA_POSITIVE",
            rwa > 0,
            "error",
            "Risk-weighted assets are greater than zero."
            if rwa > 0
            else "Risk-weighted assets must be greater than zero.",
            [crar["id"]],
        )
    validation = _crar_validation_artifact(state)
    if validation is not None:
        message = validation.get("content", {}).get("message", "")
        failed = "Risk-weighted assets must be greater than zero" in message
        if not failed:
            return result(
                "DCCB_006_RWA_POSITIVE",
                True,
                "info",
                "RWA positivity was not checked because no CRAR computation exists.",
                [validation["id"]],
            )
        return result(
            "DCCB_006_RWA_POSITIVE",
            False,
            "error",
            "Risk-weighted assets must be greater than zero.",
            [validation["id"]],
        )
    return None


def check_dccb_threshold_classification(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "dccb_audit":
        return None
    crar = _crar_artifact(state)
    if crar is None:
        return None
    content = crar.get("content", {})
    computed_status = (
        "compliant"
        if float(content.get("computedCrar", 0.0)) >= float(content.get("threshold", 9.0))
        else "non-compliant"
    )
    output_status = state.get("graph", {}).get("nodes", {}).get("output:compliance", {}).get("content")
    return result(
        "DCCB_007_THRESHOLD_CLASSIFICATION",
        output_status == computed_status,
        "error",
        f"Computed threshold classification is {computed_status}."
        if output_status == computed_status
        else f"Output status {output_status} does not match computed status {computed_status}.",
        [crar["id"], "output:compliance"],
    )


def check_dccb_reported_status_match(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "dccb_audit":
        return None
    crar = _crar_artifact(state)
    if crar is None:
        return None
    content = crar.get("content", {})
    reported_status = content.get("reportedStatus")
    if not reported_status:
        return result(
            "DCCB_008_REPORTED_STATUS_MATCH",
            True,
            "info",
            "No reported compliance status was provided.",
            [crar["id"]],
        )
    computed_status = (
        "compliant"
        if float(content.get("computedCrar", 0.0)) >= float(content.get("threshold", 9.0))
        else "non-compliant"
    )
    normalized = str(reported_status).strip().lower()
    return result(
        "DCCB_008_REPORTED_STATUS_MATCH",
        normalized == computed_status,
        "error",
        "Reported compliance status matches computed status."
        if normalized == computed_status
        else f"Reported status {reported_status} does not match computed status {computed_status}.",
        [crar["id"]],
    )


def check_dccb_reported_crar_match(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("taskAst", {}).get("meta", {}).get("domain") != "dccb_audit":
        return None
    crar = next(
        (
            artifact
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "dccb_crar_computation"
        ),
        None,
    )
    if crar is None:
        return result(
            "DCCB_003_REPORTED_CRAR_MATCH",
            True,
            "info",
            "Reported CRAR match not checked because no computation exists yet.",
        )
    content = crar.get("content", {})
    reported = content.get("reportedCrar")
    if reported is None:
        return result(
            "DCCB_003_REPORTED_CRAR_MATCH",
            True,
            "info",
            "No reported CRAR was provided, so no reported-vs-computed match was required.",
            [crar["id"]],
        )
    computed = float(content.get("computedCrar", 0.0))
    difference = abs(float(reported) - computed)
    return result(
        "DCCB_003_REPORTED_CRAR_MATCH",
        difference <= 0.01,
        "error",
        "Reported CRAR matches computed CRAR."
        if difference <= 0.01
        else (
            "Reported CRAR does not match computed CRAR: "
            f"reported = {float(reported):.2f}%, computed = {computed:.2f}%, "
            f"difference = {difference:.2f} percentage points."
        ),
        [crar["id"]],
    )


def run_invariants(state: dict[str, Any]) -> list[dict[str, Any]]:
    checks = [
        check_root_goal_exists(state),
        check_edge_endpoints(state),
        check_graph_duplicate_edges(state),
        check_final_output_lineage_to_goal(state),
        check_evidence_nodes_have_evidence_ref(state),
        check_rejected_claim_reason(state),
        check_final_claim_confidence(state),
        check_final_confidence_weakest_link(state),
        check_confidence_range(state),
        check_no_unresolved_contradictions(state),
        check_claim_support(state),
        check_required_outputs(state),
        check_final_output_lineage(state),
        check_numeric_output_trace(state),
        check_domain_invariants_have_authority(state),
        check_authority_sensitive_outputs(state),
        check_resolved_inputs_have_hash(state),
        check_evidence_rows_reference_hash(state),
        check_reconciliation_does_not_mutate_source(state),
        check_reconciliation_requires_confirmation(state),
        check_code_changed_files_hashed(state),
        check_code_diff_has_lineage(state),
        check_code_no_unconditional_auth_allow(state),
        check_code_no_secret_literal(state),
        check_code_test_status_recorded(state),
        check_code_final_risk_has_evidence(state),
        check_code_review_terminal_status_valid(state),
        check_dccb_capital_components_present(state),
        check_dccb_numeric_fields_valid(state),
        check_dccb_rwa_positive(state),
        check_dccb_crar_formula(state),
        check_dccb_crar_threshold(state),
        check_dccb_reported_crar_match(state),
        check_dccb_threshold_classification(state),
        check_dccb_reported_status_match(state),
    ]
    return [check for check in checks if check is not None]


def _crar_artifact(state: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            artifact
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "dccb_crar_computation"
        ),
        None,
    )


def _crar_validation_artifact(state: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            artifact
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "dccb_crar_input_validation"
        ),
        None,
    )


def _code_review_artifact(state: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            artifact
            for artifact in state.get("artifacts", [])
            if artifact.get("type") == "code_review_result"
        ),
        None,
    )
