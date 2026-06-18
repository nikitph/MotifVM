# MotifVM Demo Script

## 1. State the Claim

MotifVM is an invariant-checked reasoning runtime. It turns model and tool outputs into authorized `StatePatch` transitions over explicit `CognitiveState`.

## 2. Show a Clean Run

```bash
python3 -m motifvm run "Verify CRAR using examples/crar_good.csv" --domain dccb_audit
python3 -m motifvm report
```

Point out the terminal state, input hash, authority refs, and pass history.

## 3. Show a Structured Failure

```bash
python3 -m motifvm run "Verify CRAR using examples/crar_mismatch.csv" --domain dccb_audit
python3 -m motifvm report
```

Point out `committed_failed`, `failureClass: reconciliation_required`, and the reconciliation patch.

## 4. Show Repository Code Review

```bash
python3 -m motifvm run-task \
  "Review this repository diff for security risk" \
  --domain code_review \
  --input examples/code_review/repo_helper
```

Point out changed-file hashes and line-level evidence.

## 5. Export and Verify

```bash
python3 -m motifvm export-audit current
python3 -m motifvm verify-pack audit_pack/<commit-id>
```

The close: MotifVM does not ask the audience to trust the answer. It exports a bundle that can be checked.
