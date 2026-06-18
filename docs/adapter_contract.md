# Artifact Adapter Contract

An `ArtifactAdapter` is a device driver for MotifVM. It translates messy external artifacts into stable evidence and normalized facts.

## Required Fields

- `adapter_id`
- `version`
- supported media or path types
- deterministic `adapt(input_ref, path)` function

## Required Output

The adapter must emit an `AdapterResult` containing:

- adapter id and version
- input id
- path
- content hash
- zero or more resolved input artifacts
- `EvidenceRef[]`
- `ExtractedFact[]`

## Rules

- Adapters must not mutate `CognitiveState`.
- Adapters must not emit terminal claims.
- Every `EvidenceRef` must include an input hash and stable locator.
- Every `ExtractedFact` must reference an existing `EvidenceRef`.
- Adapter outputs must be schema-valid and verifier-checkable.
