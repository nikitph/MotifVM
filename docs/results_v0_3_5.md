# MotifVM v0.3.5 Results

## Summary

MotifVM v0.3.5 completes the 0.3.x reliability track. The runtime now has adversarial evaluation, terminal failure classes, patch authorization, independent audit-pack verification, realistic fixture data, and a public demo package.

The main result is that MotifVM is no longer only a clean-path reasoning runtime. It now preserves and reports failed states with enough structure to distinguish invalid inputs, reconciliation-required evidence conflicts, computation blocks, and detected security risks.

## Implemented Scope

### v0.3.0: Adversarial Suite

- Added 20 adversarial fixtures under `adversarial/`.
- Added `motifvm/adversarial.py`.
- Added `make adversarial`.
- Added expected-outcome checking with:
  - terminal status correctness
  - failed invariant correctness
  - failure class correctness
- Added outputs:
  - `.motifvm/adversarial_outputs/adversarial_results.csv`
  - `.motifvm/adversarial_outputs/failure_taxonomy.json`

### v0.3.1: Failure Taxonomy

- Added `motifvm/failure.py`.
- Failed terminal states now commit `failureClass`.
- Reports include `Failure Class`.
- Covered classes include:
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

### v0.3.2: Patch Permission System

- Added `motifvm/patch_auth.py`.
- Domain-pass patches are authorized before application.
- LLM patch validation rejects source mutation, direct reconciliation patches, input-manifest mutation, and TaskAST mutation.
- Role policies are explicit for:
  - `llm`
  - `domain_pass`
  - `runtime`
  - `reconciliation`

### v0.3.3: Audit-Pack Verifier

- Added `motifvm/verify_pack.py`.
- Added CLI:

```bash
python3 -m motifvm verify-pack <audit-pack-dir>
```

- Verifier checks:
  - required pack files
  - input hashes
  - authority hashes when source files are present
  - graph endpoints
  - lineage references
  - reconciliation patch policy
  - report status consistency

### v0.3.4: Minimal Realistic Dataset

- Added DCCB fixture variants under `datasets/dccb/`.
- Added code-review diff variants under `datasets/code_review/`.
- The dataset is intentionally small and transparent rather than benchmark-sized.

### v0.3.5: Public Demo Package

- Added `demo/README.md`.
- Added `demo/expected_results.md`.
- Added `demo/run_all.sh`.
- Added offline graph explorer copy under `demo/graph_explorer/index.html`.
- Generated demo audit packs are ignored under `demo/audit_packs/`.

## Expected Adversarial Outcome

The adversarial suite is expected to classify all 20 cases correctly:

```text
cases: 20
status_correct: 20 / 20
failed_invariant_correct: 20 / 20
failure_class_correct: 20 / 20
```

Expected failure taxonomy:

```json
{
  "computation_blocked": 2,
  "input_invalid": 3,
  "reconciliation_required": 3,
  "security_risk_detected": 8
}
```

## Verification Commands

The v0.3.5 release gate is:

```bash
make test
make demo
make eval
make adversarial
python3 -m motifvm verify-pack .motifvm/demo_outputs/dccb_mismatch/audit_pack
./demo/run_all.sh
```

Observed results:

```text
make test
12 tests OK
py_compile motifvm/*.py OK

make demo
Demo outputs written to .motifvm/demo_outputs

make eval
cases: 7
terminal_status_accuracy: 1.0
failed_invariant_accuracy: 1.0
reconciliation_accuracy: 1.0
lineage_completeness: 1.0
authority_completeness: 1.0
input_hash_completeness: 1.0
schema_validation_failures: 0

make adversarial
cases: 20
status_correct: 20 / 20
failed_invariant_correct: 20 / 20
failure_class_correct: 20 / 20

verify-pack
Audit pack verified

demo/run_all.sh
All cases passed.
```

## Observation

The important change in 0.3.x is not a larger fixture count. It is that failed states now have operational meaning. A mismatch, malformed input, blocked computation, and unsafe code diff all terminate as committed states with distinct failure classes, graph evidence, invariant records, and exportable audit packs.

That makes MotifVM closer to a reasoning runtime than a demo pipeline: it can preserve why it refused, why it reconciled, and why an independent verifier should trust the exported trace.
