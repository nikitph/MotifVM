from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path

from .runtime import run_task


def run_adversarial(root: Path, expected_path: Path | None = None) -> Path:
    expected_path = expected_path or (root / "adversarial" / "expected.json")
    cases = json.loads(expected_path.read_text(encoding="utf-8"))
    output = root / ".motifvm" / "adversarial_outputs"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    rows = []
    taxonomy = Counter()
    for case in cases:
        state = run_task(case["request"], root=root, domain=case["domain"], input_files=case.get("inputs", []))
        failed = [
            invariant["invariantId"]
            for invariant in state.get("invariants", [])
            if not invariant.get("passed") and invariant.get("severity") == "error"
        ]
        failed_joined = ";".join(failed)
        failure_class = state.get("failureClass") or ""
        if failure_class:
            taxonomy[failure_class] += 1
        rows.append(
            {
                "case": case["case"],
                "domain": case["domain"],
                "expected_status": case["expectedStatus"],
                "actual_status": state.get("status"),
                "status_correct": _bool(case["expectedStatus"] == state.get("status")),
                "expected_failed_invariant": case["expectedFailedInvariant"],
                "actual_failed_invariant": failed_joined,
                "failed_invariant_correct": _bool(_matches(case["expectedFailedInvariant"], failed)),
                "expected_failure_class": case.get("expectedFailureClass", ""),
                "actual_failure_class": failure_class,
                "failure_class_correct": _bool(case.get("expectedFailureClass", "") == failure_class),
            }
        )
    _write_csv(output / "adversarial_results.csv", rows)
    (output / "failure_taxonomy.json").write_text(
        json.dumps(dict(sorted(taxonomy.items())), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def _matches(expected: str, actual: list[str]) -> bool:
    if not expected:
        return len(actual) == 0
    return expected in actual


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _bool(value: bool) -> str:
    return "yes" if value else "no"


def main() -> None:
    output = run_adversarial(Path.cwd())
    print(f"Adversarial outputs written to {output}")


if __name__ == "__main__":
    main()
