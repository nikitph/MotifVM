# Release Notes

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
