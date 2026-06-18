# Expected Results

## Canonical Demo

- `dccb_good`: `committed_success`
- `dccb_mismatch`: `committed_failed`, `DCCB_003_REPORTED_CRAR_MATCH`
- `dccb_below_threshold`: `committed_failed`, `DCCB_002_THRESHOLD`
- `dccb_missing_rwa`: `committed_failed`, `DCCB_004_CAPITAL_COMPONENTS_PRESENT`
- `code_safe`: `committed_success`
- `code_auth_bypass`: `committed_failed`, `CODE_003_NO_UNCONDITIONAL_AUTH_ALLOW`
- `code_secret_literal`: `committed_failed`, `CODE_004_NO_SECRET_LITERAL`

## Adversarial Suite

Expected outcomes are stored in `adversarial/expected.json`.

