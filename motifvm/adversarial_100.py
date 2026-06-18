from __future__ import annotations

import csv
import json
import shutil
import time
from collections import Counter
from pathlib import Path

from .audit import export_audit_pack
from .runtime import run_task
from .verify_pack import verify_pack


def run_adversarial_100(root: Path) -> Path:
    base_cases = json.loads((root / "adversarial" / "expected.json").read_text(encoding="utf-8"))
    cases = _expand_cases(base_cases)
    output = root / ".motifvm" / "adversarial_100_outputs"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    rows = []
    taxonomy = Counter()
    for index, case in enumerate(cases, start=1):
        started = time.time()
        state = run_task(case["request"], root=root, domain=case["domain"], input_files=case.get("inputs", []))
        duration = time.time() - started
        failed = [
            invariant["invariantId"]
            for invariant in state.get("invariants", [])
            if not invariant.get("passed") and invariant.get("severity") == "error"
        ]
        pack = export_audit_pack(root, state["parentCommit"], output / "packs" / case["case"])
        pack_ok, _issues = verify_pack(pack)
        failure_class = state.get("failureClass") or ""
        if failure_class:
            taxonomy[failure_class] += 1
        expected_positive = case["expectedStatus"] == "committed_failed"
        actual_positive = state.get("status") == "committed_failed"
        rows.append(
            {
                "index": str(index),
                "case": case["case"],
                "category": case["category"],
                "domain": case["domain"],
                "expected_status": case["expectedStatus"],
                "actual_status": state.get("status"),
                "status_correct": _bool(case["expectedStatus"] == state.get("status")),
                "expected_failed_invariant": case["expectedFailedInvariant"],
                "actual_failed_invariant": ";".join(failed),
                "failed_invariant_correct": _bool(_matches(case["expectedFailedInvariant"], failed)),
                "expected_failure_class": case.get("expectedFailureClass", ""),
                "actual_failure_class": failure_class,
                "failure_class_correct": _bool(case.get("expectedFailureClass", "") == failure_class),
                "pack_verified": _bool(pack_ok),
                "false_positive": _bool(actual_positive and not expected_positive),
                "false_negative": _bool(expected_positive and not actual_positive),
                "runtime_duration": f"{duration:.4f}",
                "llm_calls": str(len(state.get("llmCalls", []))),
            }
        )
    _write_csv(output / "results.csv", rows)
    _write_summary(output / "summary.md", rows, taxonomy)
    return output


def _expand_cases(base_cases: list[dict]) -> list[dict]:
    pools = {
        "dccb_clean_messy_numeric": [case for case in base_cases if case["domain"] == "dccb_audit" and case["expectedStatus"] == "committed_success"],
        "dccb_invalid_reconciliation": [case for case in base_cases if case["domain"] == "dccb_audit" and case["expectedStatus"] == "committed_failed"],
        "code_safe_security": [case for case in base_cases if case["domain"] == "code_review" and case["expectedStatus"] == "committed_success"],
        "code_adversarial_obfuscated": [case for case in base_cases if case["domain"] == "code_review" and case["expectedStatus"] == "committed_failed"],
    }
    expanded = []
    for category, pool in pools.items():
        for index in range(25):
            source = dict(pool[index % len(pool)])
            source["case"] = f"{category}_{index + 1:02d}_{source['case']}"
            source["category"] = category
            expanded.append(source)
    return expanded


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(path: Path, rows: list[dict[str, str]], taxonomy: Counter) -> None:
    total = len(rows)
    lines = [
        "# Adversarial-100 Summary",
        "",
        f"- cases: {total}",
        f"- terminal accuracy: {_accuracy(rows, 'status_correct'):.4f}",
        f"- failed invariant accuracy: {_accuracy(rows, 'failed_invariant_correct'):.4f}",
        f"- failure class accuracy: {_accuracy(rows, 'failure_class_correct'):.4f}",
        f"- pack verifier pass rate: {_accuracy(rows, 'pack_verified'):.4f}",
        f"- false positive rate: {_accuracy(rows, 'false_positive'):.4f}",
        f"- false negative rate: {_accuracy(rows, 'false_negative'):.4f}",
        f"- total LLM calls: {sum(int(row['llm_calls']) for row in rows)}",
        "",
        "## Failure Taxonomy",
        "",
    ]
    for key, value in sorted(taxonomy.items()):
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _matches(expected: str, actual: list[str]) -> bool:
    if not expected:
        return len(actual) == 0
    return expected in actual


def _accuracy(rows: list[dict[str, str]], field: str) -> float:
    return sum(1 for row in rows if row[field] == "yes") / len(rows)


def _bool(value: bool) -> str:
    return "yes" if value else "no"


def main() -> None:
    output = run_adversarial_100(Path.cwd())
    print(f"Adversarial-100 outputs written to {output}")


if __name__ == "__main__":
    main()
