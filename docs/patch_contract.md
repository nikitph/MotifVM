# StatePatch Contract

`StatePatch` is the only mutation vehicle for `CognitiveState`.

## Patch Contents

- nodes to add
- nodes to update
- edges to add
- artifacts to add
- decisions to add
- task updates
- status update
- motif support delta

## Authorization

Every patch has an implied role:

- `domain_pass`
- `llm`
- `runtime`
- `reconciliation`

The runtime validates schema and authorizes the role before applying the patch. LLM patches may add bounded artifacts but may not alter terminal state, invariant results, input manifests, authority refs, or source artifacts.

## Timeline

Every accepted or rejected patch is recorded in `patchTimeline` and exported in audit packs.
