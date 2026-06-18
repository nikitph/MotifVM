# Audit Pack Contract

An audit pack is a portable evidence bundle for a committed MotifVM state.

## Required Files

- `state.json`
- `report.md`
- `graph.json`
- `graph.dot`
- `graph.mmd`
- `lineage.json`
- `invariants.json`
- `inputs_manifest.json`
- `extracted_facts.json`
- `llm_calls.json`
- `reconciliation_patch.json`
- `patch_timeline.json`
- `patch_timeline.md`

## Verification

`verify-pack` checks:

- required files
- input hashes
- authority hashes and section hashes
- graph endpoints
- lineage references
- reconciliation policy
- report status consistency
- patch timeline shape
- adapter output conformance

The verifier does not certify domain completeness. It verifies that the exported state is internally consistent with the MotifVM contract.
