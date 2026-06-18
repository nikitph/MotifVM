# Release Notes

## v0.6.5

MotifVM v0.6.5 implements the cognitive compiler layer above the frozen kernel. Every run now receives a `MotifFrame`, a motif-gap-derived `ReasoningPlan`, an adaptive verification policy, and replan metadata when fatal invariants require a different response path.

### Added

- `MotifFrame`:
  - required motif vector
  - supported motif vector
  - motif gap
  - consequence-weighted risk
  - selected compiler policies
- `config/pass_effects.json` covering every runtime pass.
- Motif-aware planner that scores pass effects against motif gaps and emits dependency-safe pass plans.
- Adaptive verification policies:
  - `light`
  - `standard`
  - `strict`
- Failure-driven replanning for:
  - missing lineage
  - missing authority
  - reconciliation requirements
  - computation blocking
  - invalid input
  - security-risk detection
- Audit-pack compiler exports:
  - `motif_frame.json`
  - `reasoning_plan.json`
  - `reasoning_plans.json`
- Report sections for motif risk, selected policies, selected passes, verification rationale, and replan events.
- Compiler evaluation harness:

```bash
make compiler-eval
```

### Verification

See `docs/results_v0_6_5.md`.

## v0.5.4

MotifVM v0.5.4 freezes the kernel boundary around artifact adapters and the `ExtractedFact` normal form. CSV, git diff, and repository inputs now enter through `ArtifactAdapter` contracts that emit hash-bound `EvidenceRef` records and normalized `ExtractedFact` records before any domain pass constructs claims.

### Added

- Core adapter primitives:
  - `ArtifactAdapter`
  - `AdapterResult`
  - `EvidenceRef`
  - `ExtractedFact`
- Built-in adapters:
  - CSV adapter
  - git diff adapter
  - repository diff adapter
- Adapter conformance runner:

```bash
make adapter-conformance
```

- Audit-pack `extracted_facts.json` export.
- Pack verifier checks for adapter output conformance.
- Kernel freeze docs:
  - `docs/kernel_contract.md`
  - `docs/adapter_contract.md`
  - `docs/fact_contract.md`
  - `docs/patch_contract.md`
  - `docs/audit_pack_contract.md`
- LaTeX paper:
  - `docs/motifvm_core_freeze_paper.tex`
  - `docs/motifvm_core_freeze_paper.pdf`

### Verification

See `docs/results_v0_5_4.md`.

## Frozen Proof Table

| Version | Core proof |
| --- | --- |
| 0.1.8 | kernel + two-domain audit packs |
| 0.2.5 | provider boundary + authority hashing + eval |
| 0.3.5 | adversarial reliability + patch authorization + pack verifier |
| 0.4.5 | repository-scale inputs + LLM narrative boundary + authority section citations + patch timeline + adversarial-100 |
| 0.5.4 | adapter boundary + ExtractedFact normal form + kernel freeze contracts |
| 0.6.5 | cognitive compiler + MotifFrame + motif-aware planning + adaptive verification + replanning |

## v0.4.5

MotifVM v0.4.5 completes the 0.4.x scale and integration track. The runtime can now review repository-style code inputs, export patch timelines, cite authority sections, run a 100-case adversarial suite, and use DeepSeek or the mock provider for bounded final narrative emission without letting the model alter terminal facts.

### Added

- Repository input resolver for code review.
- Changed-file manifest entries for repository diffs.
- Multi-file diff evidence extraction and helper-indirection auth-bypass detection.
- Bounded `CALL_EMIT` LLM narrative artifact.
- Explicit LLM patch authorization for non-critical narrative emission.
- Section-level authority citations with `sectionId`, `quotedRuleExcerpt`, `effectiveDate`, `retrievedAt`, and `sectionHash`.
- Audit-pack patch timeline exports:
  - `patch_timeline.json`
  - `patch_timeline.md`
- Graph explorer patch timeline view.
- `make adversarial-100` and `python3 -m motifvm adversarial-100`.
- External demo readiness docs:
  - `docs/demo_script.md`
  - `docs/architecture_deep_dive.md`
  - `docs/threat_model.md`
  - `docs/limitations.md`

### Verification

See `docs/results_v0_4_5.md` for the detailed run report.

## v0.3.5

MotifVM v0.3.5 completes the 0.3.x hardening track: adversarial evaluation, failure taxonomy, patch authorization, independent audit-pack verification, a small realistic dataset, and a public demo package.

### Added

- Adversarial evaluation suite with 20 fixtures across DCCB CRAR and code-review security.
- `make adversarial` and `python3 -m motifvm adversarial`.
- `adversarial_results.csv` and `failure_taxonomy.json` outputs.
- Runtime `failureClass` committed on failed terminal states.
- Failure taxonomy covering invalid input, reconciliation requirements, computation blocking, and security-risk detection.
- Patch authorization layer for LLM, domain pass, runtime, and reconciliation roles.
- Independent audit-pack verifier:

```bash
python3 -m motifvm verify-pack <audit-pack-dir>
```

- Minimal realistic dataset under `datasets/`.
- Public demo package under `demo/`.

### Verification

Final v0.3.5 gate:

```text
make test
make demo
make eval
make adversarial
python3 -m motifvm verify-pack .motifvm/demo_outputs/dccb_mismatch/audit_pack
./demo/run_all.sh
```

See `docs/results_v0_3_5.md` for the detailed run report.

## v0.2.5

MotifVM v0.2.5 advances the v0.1.8 kernel into an evaluable runtime with stronger provider boundaries, validation, authority provenance, code-review checks, an offline graph explorer, and an evaluation harness.

### Added

- DeepSeek structured LLM adapter using OpenAI-compatible chat completions.
- Safe API-key handling through `DEEPSEEK_API_KEY`; keys are not stored in source, config, state, or audit packs.
- Stronger schema validation helpers for:
  - `StatePatch`
  - `CognitiveState`
  - `EvidenceRef`
  - `AuthorityRef`
  - `DomainProfile`
  - `PassSpec`
- Expanded code-review checks:
  - `shell=True`
  - `eval` / `exec`
  - disabled TLS verification
  - SQL string interpolation
  - unsafe deserialization
- External authority source documents under `authority_sources/`.
- Authority refs with source document locations and hashes when available.
- Offline audit-pack graph explorer:
  - `static/graph_explorer.html`
- Evaluation harness:
  - `eval/expected.json`
  - `motifvm/eval.py`
  - `make eval`

### Verification

`make test`:

```text
8 tests OK
```

`make demo`:

```text
7 canonical cases executed
```

`make eval`:

```text
terminal_status_accuracy: 1.0
failed_invariant_accuracy: 1.0
reconciliation_accuracy: 1.0
lineage_completeness: 1.0
authority_completeness: 1.0
input_hash_completeness: 1.0
schema_validation_failures: 0
```

### Notes

The DeepSeek adapter is implemented and available with:

```bash
DEEPSEEK_API_KEY=... python3 -m motifvm run-task "..." --llm deepseek
```

Do not commit API keys or write them to `.env` files inside this repository.
