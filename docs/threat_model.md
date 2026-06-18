# MotifVM Threat Model

## Protected Assets

- `CognitiveState`
- input manifests and hashes
- authority refs and source hashes
- invariant results
- terminal state
- audit packs

## Threats Considered

- malformed inputs
- adversarial numeric fields
- unsafe code diffs
- LLM attempts to modify terminal facts
- unauthorized source mutation
- missing lineage
- audit pack tampering

## Controls

- schema validation
- patch authorization
- domain and universal invariants
- input and authority hashing
- failure taxonomy
- independent pack verification
- patch timeline export

## Not Guaranteed

MotifVM does not prove that every domain rule is complete, every source authority is legally current, or every possible security bug is detected. It proves that the runtime preserved the declared evidence, authority, transition, and invariant boundaries for the task it ran.
