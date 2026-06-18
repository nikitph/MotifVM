# Release Notes

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
