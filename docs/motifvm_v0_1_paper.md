# MotifVM v0.1: Invariant-Checked Cognitive State

## 1. Problem

LLM agents often lack durable structured reasoning state. They can produce fluent answers, but intermediate claims, evidence, tool results, contradictions, and failure states are frequently trapped in prompt context or free text.

## 2. Insight

LLMs should propose state transitions, not own state. MotifVM treats language-model output, deterministic tools, and domain passes as producers of typed `StatePatch` objects. The runtime validates patches, applies them transactionally, checks invariants, and commits success or failure states.

## 3. Architecture

The kernel is:

`CognitiveState + StatePatch -> validate -> apply -> verify -> commit -> report`

Core structures include `TaskAST`, `ReasoningGraph`, artifacts, decisions, invariant results, authority refs, input manifests, and commit records.

## 4. Motif Diagnosis

Motif diagnosis estimates what structural concerns a task requires: representation, state, storage, addressing, invariant, authority, reconciliation, scheduling, terminal state, and related motifs. The runtime compares required support with current support and uses the gap to prioritize passes.

## 5. DCCB Audit Demo

The DCCB profile verifies CRAR computations from CSV inputs. It computes CRAR, checks formula and threshold invariants, detects reported-vs-computed mismatches, preserves source input hashes, and emits a reconciliation patch without mutating the source.

## 6. Code Review Demo

The code-review profile uses the same runtime to inspect code diffs. It creates line-level evidence refs, detects unconditional authorization bypasses and secret literals, records terminal status, and exports the same audit pack structure.

## 7. Failure-State Semantics

Failed states are first-class outputs. `committed_failed` means MotifVM preserved the evidence state, invariant failures, graph, lineage, and artifacts. A failure is not discarded; it is often the main result.

## 8. Limitations

The current implementation uses deterministic mock LLM calls, simple code-review heuristics, and domain-profile authority refs rather than external regulatory retrieval. It is a kernel and demo release, not a production static analyzer or banking compliance system.

## 9. Roadmap

Next steps include richer profile loading, stronger schema validation, real LLM provider adapters, deeper code analysis, visual graph inspection, and external authority source retrieval.
