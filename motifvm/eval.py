from __future__ import annotations

import csv
import json
import shutil
import time
from pathlib import Path

from .runtime import run_task


def run_evaluation(root: Path, expected_path: Path | None = None) -> Path:
    expected_path = expected_path or (root / "eval" / "expected.json")
    cases = json.loads(expected_path.read_text(encoding="utf-8"))
    output = root / ".motifvm" / "eval_outputs"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    rows = []
    for case in cases:
        started = time.time()
        state = run_task(case["request"], root=root, domain=case["domain"], input_files=case.get("inputs", []))
        duration = time.time() - started
        failed = [
            invariant["invariantId"]
            for invariant in state.get("invariants", [])
            if not invariant.get("passed") and invariant.get("severity") == "error"
        ]
        failed_joined = ";".join(failed)
        reconciliation = any(artifact.get("type") == "reconciliation_patch" for artifact in state.get("artifacts", []))
        lineage = any(node.get("meta", {}).get("lineage") for node in state.get("graph", {}).get("nodes", {}).values())
        authority = bool(state.get("authorityRefs"))
        hashes = all(item.get("sha256") for item in state.get("inputManifest", []))
        schema_failures = [item for item in failed if item.startswith("SCHEMA_")]
        rows.append(
            {
                "case": case["case"],
                "domain": case["domain"],
                "expected_status": case["expectedStatus"],
                "actual_status": state.get("status"),
                "status_correct": _bool(case["expectedStatus"] == state.get("status")),
                "expected_failed_invariant": case["expectedFailedInvariant"],
                "actual_failed_invariant": failed_joined,
                "failed_invariant_correct": _bool(_matches_failed(case["expectedFailedInvariant"], failed)),
                "expected_reconciliation": _bool(case["expectedReconciliation"]),
                "actual_reconciliation": _bool(reconciliation),
                "reconciliation_correct": _bool(case["expectedReconciliation"] == reconciliation),
                "lineage_present": _bool(lineage),
                "authority_present": _bool(authority),
                "input_hashes_present": _bool(hashes),
                "schema_validation_failures": str(len(schema_failures)),
                "runtime_duration": f"{duration:.4f}",
                "llm_calls": str(len(state.get("llmCalls", []))),
            }
        )
    _write_csv(output / "evaluation.csv", rows)
    _write_summary(output / "summary.json", rows)
    return output


def _matches_failed(expected: str, actual: list[str]) -> bool:
    if not expected:
        return len(actual) == 0
    return expected in actual


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(path: Path, rows: list[dict[str, str]]) -> None:
    total = len(rows)
    summary = {
        "cases": total,
        "terminal_status_accuracy": _accuracy(rows, "status_correct"),
        "failed_invariant_accuracy": _accuracy(rows, "failed_invariant_correct"),
        "reconciliation_accuracy": _accuracy(rows, "reconciliation_correct"),
        "lineage_completeness": _accuracy(rows, "lineage_present"),
        "authority_completeness": _accuracy(rows, "authority_present"),
        "input_hash_completeness": _accuracy(rows, "input_hashes_present"),
        "schema_validation_failures": sum(int(row["schema_validation_failures"]) for row in rows),
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _accuracy(rows: list[dict[str, str]], field: str) -> float:
    return round(sum(1 for row in rows if row[field] == "yes") / len(rows), 4)


def _bool(value: bool) -> str:
    return "yes" if value else "no"


def main() -> None:
    output = run_evaluation(Path.cwd())
    print(f"Evaluation outputs written to {output}")


if __name__ == "__main__":
    main()
