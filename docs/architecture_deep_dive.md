# MotifVM Architecture Deep Dive

MotifVM is built around one transition law:

```text
CognitiveState + StatePatch -> validate -> authorize -> apply -> verify -> commit
```

## Runtime Layers

1. Execution semantics: passes emit `StatePatch`; the runtime owns mutation.
2. Evidence semantics: inputs become hashes, evidence refs, claims, invariants, and terminal states.
3. Failure semantics: failed invariants become typed committed failures, not exceptions.

## Trust Boundary

LLMs and tools are outside the state boundary. They can propose patches or narrative artifacts, but the runtime validates schema, authorizes role permissions, runs invariants, and commits the result.

## Audit Boundary

Audit packs contain state, graph, lineage, invariants, inputs, LLM calls, reconciliation patches, and patch timelines. `verify-pack` checks internal consistency without rerunning the task.
