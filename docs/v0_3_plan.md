# MotifVM v0.3 Plan

## Thesis

MotifVM does not only work on clean demos. It preserves correctness boundaries under malformed, adversarial, and ambiguous inputs by classifying terminal states, rejecting invalid patches, and exporting independently verifiable audit packs.

## v0.3.0: Adversarial Evaluation Suite

Add deliberately hostile and messy fixtures for the existing two domains.

DCCB examples:

- malformed CSV headers
- duplicate CRAR rows
- conflicting reported CRAR values
- negative RWA
- hidden whitespace / comma formatting
- percent vs decimal confusion

Code review examples:

- secret split across strings
- auth bypass via helper function
- SQL interpolation across multiline string
- eval hidden behind alias
- `shell=True` via variable
- disabled TLS through session object

Definition of done:

- `make adversarial`
- `adversarial_results.csv`
- at least 20 adversarial fixtures
- expected terminal state per fixture
- failure taxonomy generated

## v0.3.1: Failure Taxonomy

Add first-class failure classes:

- `input_invalid`
- `computation_blocked`
- `invariant_failed`
- `authority_missing`
- `lineage_missing`
- `schema_invalid`
- `llm_patch_rejected`
- `tool_failed`
- `reconciliation_required`
- `security_risk_detected`

Every committed failed state should include `failureClass`.

## v0.3.2: Patch Permission System

Make patch authorization explicit.

Patch permissions:

- `add_node`
- `modify_node_status`
- `add_edge`
- `add_artifact`
- `add_authority_ref`
- `add_reconciliation_patch`
- `modify_task_ast`
- `modify_input_manifest`

Policy:

- LLM patches cannot modify `inputManifest`.
- LLM patches cannot modify authority hashes.
- LLM patches cannot mark failed invariants as passed.
- LLM patches cannot mutate source artifacts.
- Domain passes can add claims/evidence only within their domain.

## v0.3.3: Golden Audit Pack Verifier

Add:

```bash
python3 -m motifvm verify-pack <audit-pack-dir>
```

Checks:

- input hashes match when source files are available
- lineage references resolve
- authority hashes resolve
- invariant results are internally consistent
- graph endpoints exist
- reconciliation patch obeys policy
- report terminal block matches `state.json`

## v0.3.4: Minimal Realistic Dataset

Add controlled but more varied examples:

- DCCB synthetic realistic CSV variants
- code-review real-style diff snippets

Goal: verify MotifVM survives input variation.

## v0.3.5: Public Demo Package

Package:

```text
demo/
├── README.md
├── run_all.sh
├── expected_results.md
├── audit_packs/
└── graph_explorer/
```

One command:

```bash
./demo/run_all.sh
```

