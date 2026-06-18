# MotifVM v0.2.5 Results

## Summary

MotifVM v0.2.5 builds on the v0.1.8 release-candidate kernel and adds the next phase of real-world usefulness:

- DeepSeek structured LLM adapter
- Stronger schema validation
- Expanded code-review checks
- External authority source documents
- Offline graph explorer
- Evaluation harness with explicit expected outcomes and metrics

The core MotifVM law remains intact:

```text
No pass, tool, or LLM call mutates CognitiveState directly.
Everything emits StatePatch.
Runtime validates, applies, verifies, and commits.
```

## DeepSeek Integration

Implemented:

- `DeepSeekLLMClient`
- OpenAI-compatible `/chat/completions` REST call via Python standard library
- JSON-object response mode
- retry/fallback behavior
- structured call logs with input/output hashes
- environment-only API key handling

Usage:

```bash
DEEPSEEK_API_KEY=... python3 -m motifvm run-task \
  "Review this code diff for security risk" \
  --domain code_review \
  --input examples/code_review/unsafe_auth_bypass/diff.patch \
  --llm deepseek
```

The API key is not written to state, source, commits, logs, or audit packs.

## Schema Validation

Added `motifvm/schema.py` with validators for:

- `StatePatch`
- `CognitiveState`
- `EvidenceRef`
- `AuthorityRef`
- `DomainProfile`
- `PassSpec`

Malformed patches now produce validation errors rather than runtime crashes.

## Code Review Upgrade

Added deterministic checks for:

- `shell=True`
- `eval` / `exec`
- disabled TLS verification
- SQL string interpolation
- unsafe deserialization

Existing checks remain:

- unconditional auth allow
- hardcoded secret literal

## Authority Versioning

Added external authority source documents:

- `authority_sources/dccb/crar_rules.md`
- `authority_sources/code_review/security_policy.md`

Authority refs now include source document locations and hashes when available.

## Visual Graph Explorer

Added:

- `static/graph_explorer.html`

Audit packs copy this file as `graph_explorer.html`, allowing offline inspection of exported `state.json`.

## Evaluation Harness

Added:

- `eval/expected.json`
- `motifvm/eval.py`
- `make eval`
- `python3 -m motifvm eval`

The harness evaluates:

- terminal status accuracy
- failed invariant accuracy
- reconciliation accuracy
- lineage completeness
- authority completeness
- input hash completeness
- schema validation failures
- runtime duration
- LLM call count

## Verification

### Tests

Command:

```bash
make test
```

Result:

```text
Ran 10 tests
OK
```

### Demo

Command:

```bash
make demo
```

Result:

```text
7 canonical cases executed
```

### Evaluation

Command:

```bash
make eval
```

Result:

```json
{
  "authority_completeness": 1.0,
  "cases": 7,
  "failed_invariant_accuracy": 1.0,
  "input_hash_completeness": 1.0,
  "lineage_completeness": 1.0,
  "reconciliation_accuracy": 1.0,
  "schema_validation_failures": 0,
  "terminal_status_accuracy": 1.0
}
```

## Notes

The DeepSeek adapter was implemented against DeepSeek's OpenAI-compatible API format. Live calls require `DEEPSEEK_API_KEY` in the environment. The key provided during development was not persisted or printed.

