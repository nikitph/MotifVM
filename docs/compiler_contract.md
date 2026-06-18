# Motif Compiler Contract

MotifVM v0.6.5 adds the cognitive compiler layer above the frozen kernel. The kernel still owns `CognitiveState`, `StatePatch`, invariants, terminal commits, and audit packs. The compiler decides how a task should enter that kernel.

## MotifFrame

Every run receives a `MotifFrame`:

```text
taskAst + required motif vector + supported motif vector
  -> gap
  -> consequence-weighted risk
  -> selected compiler policies
```

The frame records:

- `required`: motif demand diagnosed from the task.
- `supported`: motif support already present in state.
- `gap`: remaining unsatisfied motif demand.
- `risk`: `gap * consequence`, where consequence depends on domain and task language.
- `selectedPolicies`: policy flags such as `authority_required`, `strict_verification`, `lineage_strict_mode`, and `contradiction_scan`.

## PassEffect Registry

Every runtime pass must have metadata in `config/pass_effects.json` unless it is explicitly marked `runtimeInternal`.

Each entry declares:

- motif deltas in `strengthens`
- cost profile in `cost`
- runtime risk profile in `risk`
- known `failureModes`

The compiler refuses to build a plan when pass metadata is missing.

## Planning

The planner selects passes by scoring gap reduction against cost:

```text
score(pass) = sum(gap[motif] * effect[motif]) - cost_penalty
```

The compiler also includes dependencies and emits a topologically valid `ReasoningPlan`. High-authority and high-invariant tasks select authority and structural verification passes. Low-risk summary tasks choose cheaper light verification and skip authority extraction unless the motif frame asks for it.

## Verification Policy

Verification is selected from motif risk:

- `light`: schema and terminal checks for low-risk or scarcity-dominant tasks.
- `standard`: schema, terminal, lineage, authority, and domain invariants.
- `strict`: standard checks plus contradiction scan, confidence propagation, and pack verifier expectations.

## Replanning

Fatal invariant failures are classified and can trigger a compiler replan event:

- `lineage_missing` -> request more evidence
- `authority_missing` -> load authority sources
- `reconciliation_required` -> run reconciliation
- `computation_blocked` -> request more evidence
- `input_invalid` -> commit failure and request clean input
- `security_risk_detected` -> commit security failure

Replans are appended to `reasoningPlans`, surfaced in `replanEvents`, and recorded in the patch timeline as `motif_compiler_replan`.

## Audit Export

Audit packs export compiler decisions as first-class files:

- `motif_frame.json`
- `reasoning_plan.json`
- `reasoning_plans.json`

The independent pack verifier checks that these files exist and contain the required compiler fields.
