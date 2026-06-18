from __future__ import annotations

import hashlib
import json
from pathlib import Path


def verify_pack(path: Path) -> tuple[bool, list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    state_path = path / "state.json"
    if not state_path.exists():
        return False, [{"check": "PACK_001_STATE_PRESENT", "message": "state.json missing"}]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    graph = state.get("graph", {})
    nodes = graph.get("nodes", {})

    for item in state.get("inputManifest", []):
        source = Path(item.get("path", ""))
        if source.exists():
            actual = _tree_hash(source) if source.is_dir() else _sha256(source)
            if actual != item.get("sha256"):
                issues.append({"check": "PACK_INPUT_HASH", "message": f"Input hash mismatch: {source}"})

    for node_id, node in nodes.items():
        lineage = node.get("meta", {}).get("lineage")
        if not lineage:
            continue
        for evidence_id in lineage.get("evidenceNodeIds", []):
            if evidence_id not in nodes:
                issues.append({"check": "PACK_LINEAGE_REF", "message": f"{node_id} references missing {evidence_id}"})
        claim_id = lineage.get("claimNodeId")
        if claim_id and claim_id not in nodes:
            issues.append({"check": "PACK_LINEAGE_CLAIM", "message": f"{node_id} references missing claim {claim_id}"})

    authorities = {item.get("id"): item for item in state.get("authorityRefs", [])}
    for authority in authorities.values():
        location = str(authority.get("location") or "").split("#", 1)[0]
        expected = authority.get("sourceHash")
        if location and expected and Path(location).exists() and _sha256(Path(location)) != expected:
            issues.append({"check": "PACK_AUTHORITY_HASH", "message": f"Authority hash mismatch: {authority.get('id')}"})

    for edge in graph.get("edges", []):
        if edge.get("from") not in nodes or edge.get("to") not in nodes:
            issues.append({"check": "PACK_GRAPH_ENDPOINT", "message": f"Bad edge endpoint: {edge}"})

    for artifact in state.get("artifacts", []):
        if artifact.get("type") == "reconciliation_patch":
            content = artifact.get("content", {})
            if content.get("sourceMutated") is not False:
                issues.append({"check": "PACK_RECON_POLICY", "message": "Reconciliation patch mutates source"})
            if content.get("requiresConfirmation") is not True:
                issues.append({"check": "PACK_RECON_POLICY", "message": "Reconciliation patch lacks confirmation"})

    report = path / "report.md"
    if report.exists():
        text = report.read_text(encoding="utf-8")
        if f"Status: {state.get('status')}" not in text:
            issues.append({"check": "PACK_REPORT_STATUS", "message": "Report terminal status does not match state"})
    else:
        issues.append({"check": "PACK_REPORT_PRESENT", "message": "report.md missing"})

    for filename in (
        "graph.json",
        "graph.dot",
        "graph.mmd",
        "lineage.json",
        "invariants.json",
        "inputs_manifest.json",
        "patch_timeline.json",
        "patch_timeline.md",
    ):
        if not (path / filename).exists():
            issues.append({"check": "PACK_FILE_PRESENT", "message": f"{filename} missing"})

    timeline_path = path / "patch_timeline.json"
    if timeline_path.exists():
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        if not isinstance(timeline.get("patches"), list):
            issues.append({"check": "PACK_PATCH_TIMELINE", "message": "patch_timeline.json patches must be a list"})
        for item in timeline.get("patches", []):
            if not item.get("passName") or "authorized" not in item:
                issues.append({"check": "PACK_PATCH_TIMELINE", "message": "Patch timeline entry missing passName/authorized"})

    for authority in authorities.values():
        excerpt = authority.get("quotedRuleExcerpt")
        section_hash = authority.get("sectionHash")
        if excerpt and section_hash and hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != section_hash:
            issues.append({"check": "PACK_AUTHORITY_SECTION_HASH", "message": f"Authority section hash mismatch: {authority.get('id')}"})
        location = str(authority.get("location") or "").split("#", 1)[0]
        if excerpt and location and Path(location).exists() and excerpt not in Path(location).read_text(encoding="utf-8"):
            issues.append({"check": "PACK_AUTHORITY_EXCERPT", "message": f"Authority excerpt not found: {authority.get('id')}"})

    return not issues, issues


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


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("pack")
    args = parser.parse_args()
    ok, issues = verify_pack(Path(args.pack))
    if ok:
        print("Audit pack verified")
    else:
        for issue in issues:
            print(f"{issue['check']}: {issue['message']}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
