from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any

from .model import AdapterResult, ArtifactAdapter, EvidenceRef, ExtractedFact
from .storage import utc_now


ADAPTER_VERSION = "0.5.0"


def registry() -> list[ArtifactAdapter]:
    return [
        ArtifactAdapter("adapter:csv:v0.5", ADAPTER_VERSION, ["text/csv"], _adapt_csv),
        ArtifactAdapter("adapter:git_diff:v0.5", ADAPTER_VERSION, ["text/x-patch"], _adapt_diff),
        ArtifactAdapter("adapter:repo:v0.5", ADAPTER_VERSION, ["inode/directory"], _adapt_repo),
    ]


def adapter_for_path(path: Path) -> ArtifactAdapter | None:
    if path.is_dir():
        return _by_id("adapter:repo:v0.5")
    if path.suffix.lower() == ".csv":
        return _by_id("adapter:csv:v0.5")
    if path.suffix.lower() == ".patch":
        return _by_id("adapter:git_diff:v0.5")
    return None


def adapt_path(input_ref: dict[str, Any], path: Path) -> AdapterResult | None:
    adapter = adapter_for_path(path)
    if adapter is None:
        return None
    return adapter.adapt(input_ref, path)


def verify_adapter_result(result: AdapterResult | dict[str, Any]) -> list[str]:
    data = result.to_artifact()["content"] if isinstance(result, AdapterResult) else result
    errors = []
    evidence = {item.get("id"): item for item in data.get("evidenceRefs", [])}
    facts = data.get("extractedFacts", [])
    if not data.get("adapterId"):
        errors.append("Adapter output missing adapterId")
    if not data.get("adapterVersion"):
        errors.append("Adapter output missing adapterVersion")
    if not data.get("contentHash"):
        errors.append("Adapter output missing contentHash")
    for ref in evidence.values():
        for field in ("id", "inputId", "inputHash", "locatorType", "locator"):
            if not ref.get(field):
                errors.append(f"EvidenceRef missing {field}: {ref.get('id', '<unknown>')}")
    for fact in facts:
        if not fact.get("id") or not fact.get("kind"):
            errors.append(f"ExtractedFact missing id/kind: {fact}")
        if fact.get("evidenceRefId") not in evidence:
            errors.append(f"ExtractedFact references missing EvidenceRef: {fact.get('id')}")
        confidence = float(fact.get("confidence", -1.0))
        if not 0.0 <= confidence <= 1.0:
            errors.append(f"ExtractedFact confidence out of range: {fact.get('id')}")
    return errors


def _by_id(adapter_id: str) -> ArtifactAdapter:
    return next(adapter for adapter in registry() if adapter.adapter_id == adapter_id)


def _adapt_csv(input_ref: dict[str, Any], path: Path) -> AdapterResult:
    digest = sha256(path)
    evidence_refs = []
    facts = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for index, row in enumerate(rows, start=2):
        component = (row.get("component") or row.get("name") or "").strip().lower()
        amount = row.get("amount") or row.get("value") or ""
        if not component:
            continue
        evidence_id = f"evidence:csv:{path.stem}:{component}"
        evidence = EvidenceRef(
            evidence_id,
            input_ref["id"],
            digest,
            "row",
            str(index),
            f"{component},{amount}",
            {"path": str(path), "rowNumber": index, "component": component},
        )
        evidence_refs.append(evidence)
        facts.append(
            ExtractedFact(
                f"fact:csv:{path.stem}:{component}",
                "dccb_component",
                {"component": component, "amount": str(amount)},
                evidence_id,
                1.0,
                "adapter:csv:v0.5",
                ["dccb_audit"],
                {"path": str(path), "rowNumber": index},
            )
        )
    return AdapterResult(
        "adapter:csv:v0.5",
        ADAPTER_VERSION,
        input_ref["id"],
        str(path),
        digest,
        [_resolved_input_artifact(input_ref, path, digest, len(rows), "file")],
        evidence_refs,
        facts,
        {"rowsRead": len(rows)},
    )


def _adapt_diff(input_ref: dict[str, Any], path: Path) -> AdapterResult:
    text = path.read_text(encoding="utf-8")
    digest = sha256(path)
    evidence_refs, facts = _diff_refs_and_facts(text, str(path), input_ref["id"], digest)
    return AdapterResult(
        "adapter:git_diff:v0.5",
        ADAPTER_VERSION,
        input_ref["id"],
        str(path),
        digest,
        [_resolved_input_artifact(input_ref, path, digest, None, "file")],
        evidence_refs,
        facts,
        {"changedFiles": changed_files_from_diff(text), "diffHash": digest},
    )


def _adapt_repo(input_ref: dict[str, Any], path: Path) -> AdapterResult:
    digest = tree_hash(path)
    diff_text = repo_diff_text(path)
    diff_hash = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
    changed_files = changed_files_from_diff(diff_text)
    evidence_refs, facts = _diff_refs_and_facts(diff_text, str(path / "diff.patch"), input_ref["id"], diff_hash)
    artifacts = [_resolved_input_artifact(input_ref, path, digest, None, "repo")]
    artifacts.append(
        {
            "id": f"artifact:repo_review:{input_ref['id']}",
            "type": "repo_review_input",
            "content": {
                "inputId": input_ref["id"],
                "repoPath": str(path),
                "diffText": diff_text,
                "diffHash": diff_hash,
                "changedFiles": changed_files,
            },
            "producedBy": "adapter:repo:v0.5",
            "timestamp": utc_now(),
        }
    )
    for index, rel_path in enumerate(changed_files, start=1):
        file_path = path / rel_path
        if file_path.exists() and file_path.is_file():
            file_hash = sha256(file_path)
            artifacts.append(_resolved_input_artifact({"id": f"{input_ref['id']}:file:{index}"}, file_path, file_hash, None, "repo_changed_file"))
            evidence_refs.append(
                EvidenceRef(
                    f"evidence:repo_file:{rel_path}".replace("/", "_"),
                    f"{input_ref['id']}:file:{index}",
                    file_hash,
                    "file",
                    rel_path,
                    rel_path,
                    {"repoPath": str(path), "path": str(file_path)},
                )
            )
            facts.append(
                ExtractedFact(
                    f"fact:repo_changed_file:{rel_path}".replace("/", "_"),
                    "repo_changed_file",
                    {"path": rel_path},
                    f"evidence:repo_file:{rel_path}".replace("/", "_"),
                    1.0,
                    "adapter:repo:v0.5",
                    ["code_review"],
                    {"repoPath": str(path), "path": str(file_path)},
                )
            )
    return AdapterResult(
        "adapter:repo:v0.5",
        ADAPTER_VERSION,
        input_ref["id"],
        str(path),
        digest,
        artifacts,
        evidence_refs,
        facts,
        {"changedFiles": changed_files, "diffHash": diff_hash},
    )


def _resolved_input_artifact(input_ref: dict[str, Any], path: Path, digest: str, rows_read: int | None, kind: str) -> dict[str, Any]:
    return {
        "id": f"artifact:input:{input_ref['id']}",
        "type": "resolved_input",
        "content": {
            "inputId": input_ref["id"],
            "path": str(path),
            "sha256": digest,
            "rowsRead": rows_read,
            "kind": kind,
            "readAt": utc_now(),
        },
        "producedBy": "artifact_adapter",
        "timestamp": utc_now(),
    }


def _diff_refs_and_facts(diff_text: str, source: str, input_id: str, input_hash: str) -> tuple[list[EvidenceRef], list[ExtractedFact]]:
    evidence_refs = []
    facts = []
    for item in parse_added_lines(diff_text, source):
        evidence = EvidenceRef(
            item["evidenceNodeId"],
            input_id,
            input_hash,
            "line",
            item["locator"],
            item["text"],
            {"path": item["path"], "newLine": item["newLine"], "function": item.get("function")},
        )
        evidence_refs.append(evidence)
        facts.append(
            ExtractedFact(
                f"fact:line:{item['path']}:{item['newLine']}".replace("/", "_"),
                "code_added_line",
                {"text": item["text"], "path": item["path"], "newLine": item["newLine"], "function": item.get("function")},
                evidence.id,
                1.0,
                "adapter:git_diff:v0.5",
                ["code_review"],
                {"locator": item["locator"]},
            )
        )
    return evidence_refs, facts


def parse_added_lines(diff_text: str, source: str) -> list[dict[str, Any]]:
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


def changed_files_from_diff(diff_text: str) -> list[str]:
    changed = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line.removeprefix("+++ b/")
            if path not in changed:
                changed.append(path)
    return changed


def repo_diff_text(repo_path: Path) -> str:
    diff_file = repo_path / "diff.patch"
    if diff_file.exists():
        return diff_file.read_text(encoding="utf-8")
    snapshots = sorted(repo_path.glob("*.patch"))
    if snapshots:
        return snapshots[0].read_text(encoding="utf-8")
    return ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file() and ".git" not in item.parts):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        digest.update(sha256(child).encode("utf-8"))
    return digest.hexdigest()
