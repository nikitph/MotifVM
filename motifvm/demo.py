from __future__ import annotations

import csv
import shutil
import time
from pathlib import Path

from .audit import export_audit_pack
from .runtime import run_task


CASES = [
    {
        "case": "dccb_good",
        "domain": "dccb_audit",
        "request": "Verify CRAR using examples/crar_good.csv",
        "inputs": [],
    },
    {
        "case": "dccb_mismatch",
        "domain": "dccb_audit",
        "request": "Verify CRAR using examples/crar_mismatch.csv",
        "inputs": [],
    },
    {
        "case": "dccb_below_threshold",
        "domain": "dccb_audit",
        "request": "Verify CRAR using examples/crar_below_threshold.csv",
        "inputs": [],
    },
    {
        "case": "dccb_missing_rwa",
        "domain": "dccb_audit",
        "request": "Verify CRAR using examples/crar_missing_rwa.csv",
        "inputs": [],
    },
    {
        "case": "code_safe",
        "domain": "code_review",
        "request": "Review this code diff for security risk",
        "inputs": ["examples/code_review/safe/diff.patch"],
    },
    {
        "case": "code_auth_bypass",
        "domain": "code_review",
        "request": "Review this code diff for security risk",
        "inputs": ["examples/code_review/unsafe_auth_bypass/diff.patch"],
    },
    {
        "case": "code_secret_literal",
        "domain": "code_review",
        "request": "Review this code diff for security risk",
        "inputs": ["examples/code_review/secret_literal/diff.patch"],
    },
]


def run_demo(root: Path) -> Path:
    store = root / ".motifvm"
    for child in ("state", "diffs", "logs"):
        path = store / child
        if path.exists():
            shutil.rmtree(path)
    output_root = root / ".motifvm" / "demo_outputs"
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)
    rows = []
    for item in CASES:
        started = time.time()
        state = run_task(
            item["request"],
            root=root,
            domain=item["domain"],
            input_files=item["inputs"],
        )
        duration = time.time() - started
        case_dir = output_root / item["case"]
        export_audit_pack(root, state["parentCommit"], case_dir / "audit_pack")
        failed = [
            invariant["invariantId"]
            for invariant in state.get("invariants", [])
            if not invariant.get("passed") and invariant.get("severity") == "error"
        ]
        rows.append(
            {
                "case": item["case"],
                "domain": item["domain"],
                "terminal_status": state.get("status"),
                "failed_invariant": ";".join(failed),
                "lineage_present": _bool(any(_has_lineage(node) for node in state.get("graph", {}).get("nodes", {}).values())),
                "authority_present": _bool(bool(state.get("authorityRefs"))),
                "input_hashes_present": _bool(all(manifest.get("sha256") for manifest in state.get("inputManifest", []))),
                "reconciliation_patch_present": _bool(any(artifact.get("type") == "reconciliation_patch" for artifact in state.get("artifacts", []))),
                "runtime_duration": f"{duration:.4f}",
                "llm_calls": str(len(state.get("llmCalls", []))),
            }
        )
    _write_benchmark(output_root / "benchmark.csv", rows)
    return output_root


def _write_benchmark(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _has_lineage(node: dict) -> bool:
    return bool(node.get("meta", {}).get("lineage"))


def _bool(value: bool) -> str:
    return "yes" if value else "no"


def main() -> None:
    root = Path.cwd()
    output = run_demo(root)
    print(f"Demo outputs written to {output}")


if __name__ == "__main__":
    main()
