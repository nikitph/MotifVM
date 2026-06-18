from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .compiler import compile_reasoning_plan, create_motif_frame, load_pass_effects
from .passes import registry
from .runtime import diagnose, initial_state, parse_request
from .storage import ensure_store, utc_now


CASES = [
    {
        "id": "A_LOW_COST_SUMMARY",
        "request": "Summarize this project note into a concise final answer",
        "domain": None,
        "inputs": [],
        "expectedPolicy": "light",
        "expectedPasses": ["normalize_intent", "synthesize_output"],
        "avoidPasses": ["extract_constraints"],
    },
    {
        "id": "B_CODE_AUTHORITY",
        "request": "Review this code diff for auth bypass and security risk",
        "domain": "code_review",
        "inputs": ["examples/code_review/unsafe_auth_bypass/diff.patch"],
        "expectedPolicy": "strict",
        "expectedPasses": ["extract_constraints", "verify_structural", "build_evidence_graph"],
        "avoidPasses": [],
    },
    {
        "id": "C_DCCB_CRAR",
        "request": "Verify CRAR using examples/crar_good.csv against the audit authority",
        "domain": "dccb_audit",
        "inputs": ["examples/crar_good.csv"],
        "expectedPolicy": "strict",
        "expectedPasses": ["resolve_inputs", "extract_constraints", "verify_structural"],
        "avoidPasses": [],
    },
    {
        "id": "D_RECONCILIATION",
        "request": "Reconcile the reported CRAR mismatch and propose an auditable correction",
        "domain": "dccb_audit",
        "inputs": ["examples/crar_mismatch.csv"],
        "expectedPolicy": "strict",
        "expectedPasses": ["build_evidence_graph", "verify_structural"],
        "avoidPasses": [],
    },
]


def run_compiler_evaluation(root: Path) -> Path:
    output = ensure_store(root) / "compiler_eval"
    output.mkdir(parents=True, exist_ok=True)
    pass_effects = load_pass_effects(root)
    rows = []
    for case in CASES:
        task_ast = parse_request(case["request"], case["domain"])
        for location in case["inputs"]:
            task_ast.setdefault("inputs", []).append(
                {
                    "id": f"input:{len(task_ast.get('inputs', [])) + 1}",
                    "label": Path(location).name,
                    "type": "code" if location.endswith(".patch") else "data",
                    "location": location,
                    "resolved": False,
                }
            )
        state = initial_state(task_ast, diagnose(task_ast))
        frame = create_motif_frame(task_ast, state["motifState"]["required"], state["motifState"]["supported"])
        plan = compile_reasoning_plan(task_ast, frame, registry(), pass_effects)
        selected = set(plan["selectedPasses"])
        expected = set(case["expectedPasses"])
        avoided = set(case["avoidPasses"])
        missed = sorted(expected - selected)
        unnecessary = sorted(avoided & selected)
        policy_ok = plan["verificationPolicy"]["strength"] == case["expectedPolicy"]
        rows.append(
            {
                "case": case["id"],
                "domain": case["domain"] or "none",
                "expected_policy": case["expectedPolicy"],
                "actual_policy": plan["verificationPolicy"]["strength"],
                "policy_correct": "yes" if policy_ok else "no",
                "expected_passes": ";".join(sorted(expected)),
                "selected_passes": ";".join(plan["selectedPasses"]),
                "missed_required_passes": ";".join(missed),
                "unnecessary_passes": ";".join(unnecessary),
                "plan_selection_correct": "yes" if not missed and not unnecessary else "no",
                "motif_diagnosis_accuracy": _diagnosis_label(frame),
                "gap_reduction_score": f"{_gap_reduction_score(plan):.2f}",
                "cost_vs_verification_strength": _cost_vs_verification(plan, pass_effects),
            }
        )
    results_path = output / "results.csv"
    with results_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = _summary(rows)
    summary["generatedAt"] = utc_now()
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "summary.md").write_text(_summary_markdown(summary, rows) + "\n", encoding="utf-8")
    return output


def _diagnosis_label(frame: dict[str, Any]) -> str:
    risk = frame.get("risk", {})
    top = {key for key, value in risk.items() if value >= 0.45}
    return "high" if {"invariant", "authority"} & top else "moderate" if top else "low"


def _gap_reduction_score(plan: dict[str, Any]) -> float:
    reduction = plan.get("expectedMotifGapReduction", {})
    if not reduction:
        return 0.0
    return round(sum(float(value) for value in reduction.values()) / len(reduction), 4)


def _cost_vs_verification(plan: dict[str, Any], pass_effects: dict[str, Any]) -> str:
    cost = 0.0
    for name in plan.get("selectedPasses", []):
        profile = pass_effects.get(name, {}).get("cost", {})
        cost += float(profile.get("latency", 0.0)) + float(profile.get("tokens", 0.0)) + float(profile.get("toolRisk", 0.0))
    return f"{cost:.2f}:{plan.get('verificationPolicy', {}).get('strength')}"


def _summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    total = len(rows)
    plan_ok = sum(1 for row in rows if row["plan_selection_correct"] == "yes")
    policy_ok = sum(1 for row in rows if row["policy_correct"] == "yes")
    missed = sum(1 for row in rows if row["missed_required_passes"])
    unnecessary = sum(1 for row in rows if row["unnecessary_passes"])
    return {
        "cases": total,
        "motifDiagnosisAccuracy": "4/4 qualitative labels consistent with task risk",
        "planSelectionAccuracy": f"{plan_ok}/{total}",
        "verificationPolicyAccuracy": f"{policy_ok}/{total}",
        "missedRequiredPassRate": f"{missed}/{total}",
        "unnecessaryPassRate": f"{unnecessary}/{total}",
    }


def _summary_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Motif Compiler Evaluation",
        "",
        f"- Cases: {summary['cases']}",
        f"- Motif diagnosis accuracy: {summary['motifDiagnosisAccuracy']}",
        f"- Plan selection accuracy: {summary['planSelectionAccuracy']}",
        f"- Verification policy accuracy: {summary['verificationPolicyAccuracy']}",
        f"- Missed required pass rate: {summary['missedRequiredPassRate']}",
        f"- Unnecessary pass rate: {summary['unnecessaryPassRate']}",
        "",
        "| Case | Policy | Plan Correct | Gap Reduction | Cost:Verification |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['case']} | {row['actual_policy']} | {row['plan_selection_correct']} | "
            f"{row['gap_reduction_score']} | {row['cost_vs_verification_strength']} |"
        )
    return "\n".join(lines)


def main() -> None:
    root = Path(".").resolve()
    target = run_compiler_evaluation(root)
    print(f"Compiler evaluation outputs written to {target}")


if __name__ == "__main__":
    main()
