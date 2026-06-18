from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .reporting import render_report
from .graph import graph_dot, graph_json, graph_mermaid
from .storage import ensure_store, read_json, write_json


def load_commit(root: Path, commit_id: str) -> dict[str, Any]:
    store = ensure_store(root)
    if commit_id == "current":
        return read_json(store / "state" / "current.json")
    return read_json(store / "state" / "commits" / f"{commit_id}.json")


def export_audit_pack(root: Path, commit_id: str, output_dir: Path | None = None) -> Path:
    state = load_commit(root, commit_id)
    commit_label = state.get("parentCommit") or commit_id
    target = output_dir or (root / "audit_pack" / str(commit_label))
    if target.exists():
        shutil.rmtree(target)
    (target / "artifacts").mkdir(parents=True)

    write_text(target / "report.md", render_report(state))
    write_json(target / "state.json", state)
    write_json(target / "graph.json", graph_json(state))
    write_text(target / "graph.dot", graph_dot(state))
    write_text(target / "graph.mmd", graph_mermaid(state))
    write_json(target / "invariants.json", {"invariants": state.get("invariants", [])})
    write_json(target / "llm_calls.json", {"llmCalls": state.get("llmCalls", [])})
    write_json(target / "inputs_manifest.json", {"inputs": state.get("inputManifest", [])})
    write_json(target / "lineage.json", _lineage_payload(state))
    write_json(target / "patch_timeline.json", {"patches": state.get("patchTimeline", [])})
    write_text(target / "patch_timeline.md", _patch_timeline_markdown(state))

    reconciliation = [
        artifact
        for artifact in state.get("artifacts", [])
        if artifact.get("type") == "reconciliation_patch"
    ]
    write_json(target / "reconciliation_patch.json", {"patches": reconciliation})

    for artifact in state.get("artifacts", []):
        safe_id = artifact.get("id", "artifact").replace(":", "_").replace("/", "_")
        write_json(target / "artifacts" / f"{safe_id}.json", artifact)
    explorer = root / "static" / "graph_explorer.html"
    if explorer.exists():
        shutil.copyfile(explorer, target / "graph_explorer.html")
    return target


def _patch_timeline_markdown(state: dict[str, Any]) -> str:
    lines = ["# Patch Timeline", ""]
    for index, item in enumerate(state.get("patchTimeline", []), start=1):
        status = "authorized" if item.get("authorized") else "rejected"
        lines.append(f"## {index}. {item.get('passName')} ({item.get('role')}, {status})")
        if item.get("authorizationErrors"):
            lines.append(f"- authorization errors: {'; '.join(item.get('authorizationErrors', []))}")
        lines.append(f"- nodes added: {len(item.get('nodesAdded', []))}")
        lines.append(f"- edges added: {len(item.get('edgesAdded', []))}")
        lines.append(f"- artifacts added: {len(item.get('artifactsAdded', []))}")
        lines.append(f"- invariants: {item.get('invariantsBefore')} -> {item.get('invariantsAfter')}")
        delta = item.get("motifSupportDelta", {})
        if delta:
            rendered = ", ".join(f"{key}+{value}" for key, value in sorted(delta.items()))
            lines.append(f"- motif support delta: {rendered}")
        lines.append("")
    if len(lines) == 2:
        lines.append("No patches recorded.")
    return "\n".join(lines).rstrip()


def _lineage_payload(state: dict[str, Any]) -> dict[str, Any]:
    nodes = state.get("graph", {}).get("nodes", {})
    outputs = {}
    for node_id, node in nodes.items():
        lineage = node.get("meta", {}).get("lineage")
        if lineage:
            outputs[node_id] = lineage
    return {
        "authorityRefs": state.get("authorityRefs", []),
        "outputs": outputs,
    }


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
