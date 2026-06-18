# MotifVM v0.6.5 Research Release Notes

MotifVM v0.6.5 is the first complete research release of the system as a motif-aware cognitive compiler over an invariant-checked runtime kernel.

The v0.5.x line froze the kernel boundary:

```text
ArtifactAdapter -> EvidenceRef -> ExtractedFact -> StatePatch -> invariants -> terminal state -> audit pack
```

The v0.6.5 line adds the missing compiler layer:

```text
TaskAST -> MotifFrame -> ReasoningPlan -> verification policy -> StatePatch runtime
```

## Research Claim

MotifVM reframes LLM reasoning from direct answer generation into verified state transition.

LLM/tool outputs do not become truth. They become proposed `StatePatch` transitions over explicit `CognitiveState`. The runtime validates, authorizes, applies, checks invariants, commits terminal states, and exports independently verifiable audit packs.

v0.6.5 adds the planner that decides which transitions should be attempted and how strongly they should be verified.

## Added in v0.6.5

- `MotifFrame`
  - required motif vector
  - supported motif vector
  - motif gap
  - consequence-weighted risk
  - selected compiler policies
- `ReasoningPlan`
  - selected passes
  - model policy
  - tool policy
  - checkpoint policy
  - reconciliation policy
  - verification policy
  - expected motif gap reduction
  - human-readable rationale
- `PassEffect` registry in `config/pass_effects.json`
  - motif deltas
  - cost profile
  - risk profile
  - failure modes
- Motif-aware pass planning
  - scores gap reduction against cost
  - includes pass dependencies
  - emits dependency-safe pass order
- Adaptive verification policy
  - `light`
  - `standard`
  - `strict`
- Failure-driven replanning
  - `lineage_missing` -> request more evidence
  - `authority_missing` -> load authority sources
  - `reconciliation_required` -> run reconciliation
  - `computation_blocked` -> request more evidence
  - `input_invalid` -> commit failure and request clean input
  - `security_risk_detected` -> commit security failure
- Audit-pack compiler exports
  - `motif_frame.json`
  - `reasoning_plan.json`
  - `reasoning_plans.json`
- Report sections for compiler state
  - motif frame
  - top risks
  - selected policies
  - selected passes
  - verification rationale
  - replan events
- Compiler evaluation harness
  - `make compiler-eval`

## Evaluation Summary

Runtime evaluation:

```text
terminal_status_accuracy: 1.0
failed_invariant_accuracy: 1.0
reconciliation_accuracy: 1.0
lineage_completeness: 1.0
authority_completeness: 1.0
input_hash_completeness: 1.0
schema_validation_failures: 0
```

Adversarial evaluation:

```text
20-case adversarial suite:
status correctness: 20/20
failed invariant correctness: 20/20
failure class correctness: 20/20

100-case adversarial suite:
terminal accuracy: 1.0000
failed invariant accuracy: 1.0000
failure class accuracy: 1.0000
pack verifier pass rate: 1.0000
false positive rate: 0.0000
false negative rate: 0.0000
```

Compiler evaluation:

```text
motif diagnosis accuracy: 4/4 qualitative task-risk labels
plan selection accuracy: 4/4
verification policy accuracy: 4/4
missed required pass rate: 0/4
unnecessary pass rate: 0/4
```

## Release Gate

The v0.6.5 gate passed:

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

Observed:

```text
make test: OK, 21 tests
make compiler-eval: OK
make adapter-conformance: OK
make demo: OK
make eval: OK
make adversarial: OK
make adversarial-100: OK
verify-pack dccb_mismatch: Audit pack verified
```

## Example Trace

For `Verify CRAR using examples/crar_mismatch.csv`:

```text
Task
  -> MotifFrame
     high invariant/authority/reconciliation risk
  -> ReasoningPlan
     strict verification
     resolve inputs, extract constraints, build evidence, execute, verify
  -> StatePatches
     adapter output, evidence graph, CRAR computation, final output
  -> invariant failure
     DCCB_003_REPORTED_CRAR_MATCH
  -> reconciliation patch
     non-mutating correction proposal
  -> compiler replan
     action: run_reconciliation
  -> terminal state
     committed_failed, failureClass=reconciliation_required
  -> audit pack
     motif frame, reasoning plan, facts, lineage, invariants, timeline
```

## Why This Release Matters

v0.6.5 separates three layers cleanly:

- Compiler: task diagnosis, motif risk, pass selection, verification policy, replanning.
- Kernel: patch validation, authorization, invariant checking, terminal commits.
- Edge plugins: artifact adapters, domain profiles, authority sources, UI, evals.

That separation makes MotifVM credible as a runtime architecture rather than a workflow script. The kernel does not care whether evidence came from a CSV row, repository line, PDF region, API path, or database row. The compiler does not need to trust model output as truth. The verifier can inspect exported terminal states after the run.

## Tag

```text
v0.6.5
commit: a7ecf34
```
