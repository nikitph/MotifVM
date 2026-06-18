# MotifVM v0.6.5 Results

v0.6.5 implements the Motif Compiler Layer. The frozen v0.5 kernel remains intact; the new layer diagnoses task motif risk, computes pass plans from motif gaps, selects adaptive verification policy, and records replanning behavior when terminal invariants fail.

## Implemented

- `MotifFrame` with required/support/gap/risk vectors and selected compiler policies.
- `PassEffect` registry in `config/pass_effects.json` covering every runtime pass.
- Motif-aware `ReasoningPlan` generation with dependency-safe pass ordering.
- Adaptive `light`, `standard`, and `strict` verification policy selection.
- Failure-driven replanning for reconciliation, computation blocking, invalid input, missing lineage/authority, and security-risk failures.
- Audit-pack exports for `motif_frame.json`, `reasoning_plan.json`, and `reasoning_plans.json`.
- Report sections for motif risk, selected passes, verification policy, rationale, and replan events.
- Compiler evaluation harness via `make compiler-eval`.

## Compiler Evaluation

The compiler evaluation covers four paired task profiles:

| Case | Task Shape | Expected Behavior |
| --- | --- | --- |
| A_LOW_COST_SUMMARY | low-risk summary | light verification, no authority extraction |
| B_CODE_AUTHORITY | security-sensitive code review | strict verification, authority and structure passes |
| C_DCCB_CRAR | regulated CRAR audit | strict verification, evidence and authority passes |
| D_RECONCILIATION | reported mismatch reconciliation | strict verification, evidence and structural checks |

Latest local compiler-eval result:

```text
plan_selection_accuracy: 4/4
verification_policy_accuracy: 4/4
missed_required_pass_rate: 0/4
unnecessary_pass_rate: 0/4
```

The generated files are:

- `.motifvm/compiler_eval/results.csv`
- `.motifvm/compiler_eval/summary.json`
- `.motifvm/compiler_eval/summary.md`

## Verification Commands

```bash
make test
make compiler-eval
make adapter-conformance
make demo
make eval
make adversarial
make adversarial-100
python3 -m motifvm verify-pack .motifvm/demo_outputs/dccb_mismatch/audit_pack
```

Latest local gate:

```text
make test: OK, 21 tests
make compiler-eval: OK
make adapter-conformance: OK
make demo: OK
make eval: OK
make adversarial: OK, 20/20 status/invariant/failure-class checks
make adversarial-100: OK, 100/100 status/invariant/failure-class checks
verify-pack dccb_mismatch: Audit pack verified
```

Evaluation summary:

```text
terminal_status_accuracy: 1.0
failed_invariant_accuracy: 1.0
reconciliation_accuracy: 1.0
lineage_completeness: 1.0
authority_completeness: 1.0
input_hash_completeness: 1.0
schema_validation_failures: 0
```

Adversarial-100 summary:

```text
terminal accuracy: 1.0000
failed invariant accuracy: 1.0000
failure class accuracy: 1.0000
pack verifier pass rate: 1.0000
false positive rate: 0.0000
false negative rate: 0.0000
total LLM calls: 0
```

## Observation

The runtime now has two clean layers:

```text
Compiler:
TaskAST -> MotifFrame -> ReasoningPlan -> verification/replan policy

Kernel:
StatePatch -> authorization -> invariants -> terminal state -> audit pack
```

This is the missing cognitive compiler. LLM/tool outputs still cannot become truth directly. They can only participate through compiler-selected passes that emit authorized patches into the invariant-checked kernel.
