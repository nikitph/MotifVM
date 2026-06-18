from __future__ import annotations

from .model import StatePatch


PATCH_PERMISSIONS = {
    "add_node",
    "modify_node_status",
    "add_edge",
    "add_artifact",
    "add_authority_ref",
    "add_reconciliation_patch",
    "modify_task_ast",
    "modify_input_manifest",
}


ROLE_POLICIES = {
    "llm": {"add_node", "modify_node_status", "add_edge", "add_artifact"},
    "domain_pass": {"add_node", "modify_node_status", "add_edge", "add_artifact", "modify_task_ast"},
    "runtime": set(PATCH_PERMISSIONS),
    "reconciliation": {"add_node", "add_edge", "add_artifact", "add_reconciliation_patch"},
}


def authorize_patch(patch: StatePatch, role: str, domain: str | None = None) -> list[str]:
    allowed = ROLE_POLICIES.get(role, set())
    errors: list[str] = []
    required = _required_permissions(patch)
    for permission in required:
        if permission not in allowed:
            errors.append(f"{role} patch is not allowed to {permission}")
    if role == "llm":
        if any("inputManifest" in update.get("changes", {}) for update in patch.nodes_to_update):
            errors.append("LLM patch cannot modify inputManifest")
        for artifact in patch.artifacts_to_add:
            content = artifact.get("content", {})
            if content.get("sourceMutated"):
                errors.append("LLM patch cannot mutate source artifacts")
            if artifact.get("type") == "reconciliation_patch":
                errors.append("LLM patch cannot add reconciliation patches directly")
        if patch.task_updates:
            errors.append("LLM patch cannot modify TaskAST")
    if domain and role == "domain_pass":
        for node in patch.nodes_to_add:
            node_id = node.get("id", "")
            if node.get("type") in {"claim", "evidence"} and domain == "code_review" and node_id.startswith("claim:dccb"):
                errors.append("code_review pass cannot add DCCB claims")
            if node.get("type") in {"claim", "evidence"} and domain == "dccb_audit" and node_id.startswith("claim:code"):
                errors.append("dccb_audit pass cannot add code review claims")
    return errors


def _required_permissions(patch: StatePatch) -> set[str]:
    permissions = set()
    if patch.nodes_to_add:
        permissions.add("add_node")
    if patch.nodes_to_update:
        permissions.add("modify_node_status")
    if patch.edges_to_add:
        permissions.add("add_edge")
    if patch.artifacts_to_add:
        permissions.add("add_artifact")
    if any(artifact.get("type") == "reconciliation_patch" for artifact in patch.artifacts_to_add):
        permissions.add("add_reconciliation_patch")
    if patch.task_updates:
        permissions.add("modify_task_ast")
    return permissions
