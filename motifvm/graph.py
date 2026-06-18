from __future__ import annotations

from typing import Any


def graph_json(state: dict[str, Any]) -> dict[str, Any]:
    return state.get("graph", {"nodes": {}, "edges": []})


def graph_dot(state: dict[str, Any]) -> str:
    lines = ["digraph MotifVM {"]
    for node_id, node in state.get("graph", {}).get("nodes", {}).items():
        label = f"{node_id}\\n{node.get('type')}"
        lines.append(f'  "{node_id}" [label="{label}"];')
    for edge in state.get("graph", {}).get("edges", []):
        lines.append(
            f'  "{edge.get("from")}" -> "{edge.get("to")}" [label="{edge.get("relation")}"];'
        )
    lines.append("}")
    return "\n".join(lines)


def graph_mermaid(state: dict[str, Any]) -> str:
    lines = ["graph TD"]
    for edge in state.get("graph", {}).get("edges", []):
        source = _mmd_id(edge.get("from", "missing"))
        target = _mmd_id(edge.get("to", "missing"))
        relation = edge.get("relation", "")
        lines.append(f'  {source}["{edge.get("from")}"] -->|{relation}| {target}["{edge.get("to")}"]')
    if len(lines) == 1:
        lines.append('  empty["empty graph"]')
    return "\n".join(lines)


def compare_states(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    a_nodes = set(a.get("graph", {}).get("nodes", {}))
    b_nodes = set(b.get("graph", {}).get("nodes", {}))
    a_artifacts = {item.get("id") for item in a.get("artifacts", [])}
    b_artifacts = {item.get("id") for item in b.get("artifacts", [])}
    a_invariants = {item.get("invariantId"): item.get("passed") for item in a.get("invariants", [])}
    b_invariants = {item.get("invariantId"): item.get("passed") for item in b.get("invariants", [])}
    keys = sorted(set(a_invariants) | set(b_invariants))
    return {
        "terminalStatus": {"a": a.get("status"), "b": b.get("status")},
        "terminalReason": {"a": a.get("terminalReason"), "b": b.get("terminalReason")},
        "invariants": {
            key: {"a": a_invariants.get(key), "b": b_invariants.get(key)}
            for key in keys
            if a_invariants.get(key) != b_invariants.get(key)
        },
        "claims": {
            "added": sorted(node for node in b_nodes - a_nodes if node.startswith("claim:")),
            "removed": sorted(node for node in a_nodes - b_nodes if node.startswith("claim:")),
        },
        "artifacts": {
            "added": sorted(b_artifacts - a_artifacts),
            "removed": sorted(a_artifacts - b_artifacts),
        },
        "motifGap": {
            key: {
                "a": a.get("motifState", {}).get("gap", {}).get(key),
                "b": b.get("motifState", {}).get("gap", {}).get(key),
            }
            for key in sorted(
                set(a.get("motifState", {}).get("gap", {}))
                | set(b.get("motifState", {}).get("gap", {}))
            )
            if a.get("motifState", {}).get("gap", {}).get(key)
            != b.get("motifState", {}).get("gap", {}).get(key)
        },
        "lineage": {
            "aOutputs": _lineage_count(a),
            "bOutputs": _lineage_count(b),
        },
    }


def _lineage_count(state: dict[str, Any]) -> int:
    return sum(
        1
        for node in state.get("graph", {}).get("nodes", {}).values()
        if node.get("type") == "output" and node.get("meta", {}).get("lineage")
    )


def _mmd_id(value: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() else "_" for ch in value)
