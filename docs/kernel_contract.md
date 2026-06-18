# MotifVM Kernel Contract

MotifVM's kernel is the part of the system that must remain stable while adapters, domains, tools, and user interfaces evolve.

## Kernel Primitives

- `CognitiveState`
- `StatePatch`
- `PatchAuthorization`
- `Artifact`
- `ArtifactAdapter`
- `EvidenceRef`
- `ExtractedFact`
- `Claim`
- `Invariant`
- `AuthorityRef`
- `TerminalState`
- `AuditPack`
- `PackVerifier`
- `PatchTimeline`
- `ReasoningGraph`

## Transition Law

```text
CognitiveState + StatePatch
  -> schema validation
  -> role authorization
  -> apply transition
  -> invariant verification
  -> terminal commit
  -> audit-pack export
```

No adapter, pass, tool, or LLM call mutates `CognitiveState` directly.

## Kernel Boundary

Artifacts enter through adapters. Adapters emit `EvidenceRef` and `ExtractedFact`. Domain passes may convert facts into claims by proposing `StatePatch` transitions. The runtime owns validation, authorization, application, verification, commitment, and export.
