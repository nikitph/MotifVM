from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from .adapters import adapt_path, verify_adapter_result


CASES = [
    {"case": "csv_crar", "input": "examples/crar_good.csv"},
    {"case": "git_diff", "input": "examples/code_review/unsafe_auth_bypass/diff.patch"},
    {"case": "repo_diff", "input": "examples/code_review/repo_helper"},
]


def run_adapter_conformance(root: Path) -> Path:
    output = root / ".motifvm" / "adapter_conformance"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    rows = []
    for index, case in enumerate(CASES, start=1):
        path = root / case["input"]
        result = adapt_path({"id": f"input:{index}", "label": path.name, "location": str(path)}, path)
        errors = ["No adapter found"] if result is None else verify_adapter_result(result)
        if result is not None:
            (output / f"{case['case']}.json").write_text(
                json.dumps(result.to_artifact()["content"], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        rows.append(
            {
                "case": case["case"],
                "input": case["input"],
                "adapter": result.adapter_id if result else "",
                "evidence_refs": str(len(result.evidence_refs) if result else 0),
                "extracted_facts": str(len(result.extracted_facts) if result else 0),
                "schema_valid": "yes" if not errors else "no",
                "errors": "; ".join(errors),
            }
        )
    _write_csv(output / "results.csv", rows)
    return output


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    output = run_adapter_conformance(Path.cwd())
    print(f"Adapter conformance outputs written to {output}")


if __name__ == "__main__":
    main()
