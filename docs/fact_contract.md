# ExtractedFact Contract

`ExtractedFact` is the normal form between raw artifact evidence and domain claims.

## Shape

```text
ExtractedFact {
  id
  kind
  value
  evidenceRefId
  confidence
  extractedBy
  domainHints
  metadata
}
```

## Semantics

Facts are not claims. A fact says what was extracted from an artifact. A claim says what the VM believes or concludes after domain logic and invariants.

Examples:

- CSV row `tier1,120` becomes a `dccb_component` fact.
- Diff added line `return True` becomes a `code_added_line` fact.
- Repository changed file `auth.py` becomes a `repo_changed_file` fact.

Domain passes consume facts and propose claims through `StatePatch`.
