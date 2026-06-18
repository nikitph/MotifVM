from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_store(root: Path) -> Path:
    store = root / ".motifvm"
    for child in (
        "state/commits",
        "diffs",
        "logs",
        "artifacts",
        "config/prompts",
        "config/domains",
    ):
        (store / child).mkdir(parents=True, exist_ok=True)
    return store


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True)
        handle.write("\n")


def next_commit_id(store: Path) -> str:
    commits = sorted((store / "state" / "commits").glob("*.json"))
    return f"{len(commits) + 1:03d}"


def current_state_path(store: Path) -> Path:
    return store / "state" / "current.json"


def commit_state(
    store: Path,
    state: dict[str, Any],
    status: str = "committed_success",
    reason: str | None = None,
    failure_class: str | None = None,
) -> tuple[str, dict[str, Any]]:
    commit_id = next_commit_id(store)
    committed = deepcopy(state)
    committed["status"] = status
    committed["parentCommit"] = commit_id
    committed["terminalReason"] = reason
    committed["failureClass"] = failure_class
    committed.setdefault("executionLog", []).append(
        {
            "timestamp": utc_now(),
            "phase": "commit",
            "event": "state_committed",
            "details": {
                "commitId": commit_id,
                "status": status,
                "reason": reason,
                "failureClass": failure_class,
            },
        }
    )
    write_json(store / "state" / "commits" / f"{commit_id}.json", committed)
    write_json(current_state_path(store), committed)
    diff = {
        "fromCommit": state.get("parentCommit"),
        "toCommit": commit_id,
        "timestamp": utc_now(),
        "nodes": {"added": list(state.get("graph", {}).get("nodes", {}).keys())},
        "edges": {"count": len(state.get("graph", {}).get("edges", []))},
        "artifacts": {"added": [a["id"] for a in state.get("artifacts", [])]},
        "decisions": {"made": [d["id"] for d in state.get("decisions", [])]},
    }
    write_json(store / "diffs" / f"{commit_id}.json", diff)
    return commit_id, committed
