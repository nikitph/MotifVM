# MotifVM v0.4.5 Results

## Summary

MotifVM v0.4.5 is the scale-and-integration milestone. The goal was to move beyond controlled fixtures while preserving the VM law:

```text
StatePatch -> validate -> authorize -> apply -> verify -> commit
```

Implemented scope:

- v0.4.0: repository-scale code review
- v0.4.1: bounded LLM final narrative
- v0.4.2: authority section citation hardening
- v0.4.3: StatePatch timeline export and explorer view
- v0.4.4: adversarial-100 runner
- v0.4.5: external demo readiness docs

## Frozen Proof Table

| Version | Core proof |
| --- | --- |
| 0.1.8 | kernel + two-domain audit packs |
| 0.2.5 | provider boundary + authority hashing + eval |
| 0.3.5 | adversarial reliability + patch authorization + pack verifier |
| 0.4.5 | repository-scale inputs + LLM narrative boundary + authority section citations + patch timeline + adversarial-100 |

## v0.4.0 Repository-Scale Code Review

Repository directory inputs are now accepted by `--input`.

The resolver records:

- repository root hash
- changed-file manifest entries
- repository diff artifact
- line evidence across changed files

The code-review pass detects helper indirection, including the pattern where an auth-sensitive function delegates to a helper that returns unconditional `True`.

Representative command:

```bash
python3 -m motifvm run-task \
  "Review this repository diff for security risk" \
  --domain code_review \
  --input examples/code_review/repo_helper
```

## v0.4.1 Bounded LLM Narrative

`CALL_EMIT` can add an `llm_narrative` artifact through the mock or DeepSeek provider.

The LLM may summarize. It may not alter:

- terminal status
- terminal reason
- invariant results
- input manifest
- authority refs

Forbidden LLM patches are rejected before state mutation.

## v0.4.2 Authority Citation Hardening

Authority refs now include:

- `sectionId`
- `quotedRuleExcerpt`
- `effectiveDate`
- `retrievedAt`
- `sectionHash`

The verifier checks authority source hashes and section excerpt hashes.

## v0.4.3 Patch Timeline

Audit packs now export:

- `patch_timeline.json`
- `patch_timeline.md`

Each entry records:

- pass name
- role
- authorization result
- nodes added
- nodes updated
- edges added
- artifacts added
- motif support delta
- invariant counts before and after

The static graph explorer can show either graph nodes or patch timeline entries.

## v0.4.4 Adversarial-100

Added:

```bash
make adversarial-100
```

Outputs:

- `.motifvm/adversarial_100_outputs/results.csv`
- `.motifvm/adversarial_100_outputs/summary.md`
- `.motifvm/adversarial_100_outputs/packs/`

The runner expands transparent labeled pools into 100 cases and verifies each exported audit pack.

## v0.4.5 External Demo Readiness

Added:

- `docs/demo_script.md`
- `docs/architecture_deep_dive.md`
- `docs/threat_model.md`
- `docs/limitations.md`

## Verification Gate

The intended v0.4.5 gate is:

```bash
make test
make demo
make eval
make adversarial
make adversarial-100
python3 -m motifvm verify-pack .motifvm/demo_outputs/dccb_mismatch/audit_pack
python3 -m motifvm run-task "Review this repository diff for security risk" --domain code_review --input examples/code_review/repo_helper
```

Observed results:

```text
make test
16 tests OK
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

make adversarial-100
cases: 100
terminal accuracy: 1.0000
failed invariant accuracy: 1.0000
failure class accuracy: 1.0000
pack verifier pass rate: 1.0000
false positive rate: 0.0000
false negative rate: 0.0000
total LLM calls: 0

verify-pack
Audit pack verified

demo/run_all.sh
All cases passed.

repository review
State: committed_failed
Finding: finding:code:auth_helper_bypass

repository review audit pack
Audit pack verified
```

## Observation

The important v0.4.x result is that MotifVM scales the evidence machinery without loosening the runtime boundary. Repository inputs, LLM narrative, authority citations, and patch visibility all remain subordinate to the same transition law: only authorized patches mutate state, and every terminal claim is exported with verifiable evidence.
