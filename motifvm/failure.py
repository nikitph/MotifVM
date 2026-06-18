from __future__ import annotations

from typing import Iterable


FAILURE_CLASS_BY_INVARIANT = {
    "DCCB_003_REPORTED_CRAR_MATCH": "reconciliation_required",
    "DCCB_002_THRESHOLD": "invariant_failed",
    "DCCB_004_CAPITAL_COMPONENTS_PRESENT": "computation_blocked",
    "DCCB_005_NUMERIC_FIELDS_VALID": "input_invalid",
    "DCCB_006_RWA_POSITIVE": "input_invalid",
    "CODE_003_NO_UNCONDITIONAL_AUTH_ALLOW": "security_risk_detected",
    "CODE_004_NO_SECRET_LITERAL": "security_risk_detected",
    "CODE_008_NO_DANGEROUS_SUBPROCESS_SHELL": "security_risk_detected",
    "CODE_009_NO_EVAL_EXEC": "security_risk_detected",
    "CODE_010_NO_DISABLED_TLS_VERIFY": "security_risk_detected",
    "CODE_011_NO_SQL_STRING_INTERPOLATION": "security_risk_detected",
    "CODE_012_NO_UNSAFE_DESERIALIZATION": "security_risk_detected",
    "AUTH_001": "authority_missing",
    "AUTH_002": "authority_missing",
    "TRACE_001": "lineage_missing",
    "TRACE_002": "lineage_missing",
    "INPUT_001": "input_invalid",
    "INPUT_002": "input_invalid",
    "SCHEMA_001_COGNITIVE_STATE_VALID": "schema_invalid",
    "PATCH_AUTH_001": "llm_patch_rejected",
}


def classify_failure(failed_invariant_ids: Iterable[str]) -> str | None:
    for invariant_id in failed_invariant_ids:
        if invariant_id in FAILURE_CLASS_BY_INVARIANT:
            return FAILURE_CLASS_BY_INVARIANT[invariant_id]
        if invariant_id.startswith("CODE_"):
            return "security_risk_detected"
        if invariant_id.startswith("SCHEMA_"):
            return "schema_invalid"
        if invariant_id.startswith("PASSGRAPH_"):
            return "schema_invalid"
    failed = list(failed_invariant_ids)
    return "invariant_failed" if failed else None
