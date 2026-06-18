# MotifVM Workbench

Interactive local product surface for MotifVM.

The workbench makes the v0.6.5 architecture playable:

```text
domain material -> LLM proposes invariants -> MotifVM stores proposals
task -> MotifFrame -> ReasoningPlan -> StatePatches -> invariants -> terminal state
```

## Run

Use the bundled Node runtime if local Homebrew Node is broken:

```bash
export CODEX_NODE=/Users/truckx/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin
export CODEX_PNPM=/Users/truckx/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/pnpm/bin/pnpm.cjs
PATH="$CODEX_NODE:$PATH" "$CODEX_NODE/node" "$CODEX_PNPM" install
PATH="$CODEX_NODE:$PATH" "$CODEX_NODE/node" "$CODEX_PNPM" dev
```

Or, with a normal Node/npm install:

```bash
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

The API server listens on:

```text
http://127.0.0.1:8787
```

## Persistence

Local SQLite data is stored at:

```text
product/.data/motifvm_product.sqlite
```

It stores:

- domain profiles
- invariant proposals
- MotifVM runs
- graph node layouts

## LLM Invariant Proposals

Set `DEEPSEEK_API_KEY` to use DeepSeek for invariant authoring:

```bash
DEEPSEEK_API_KEY=... npm run dev
```

If no key is present, the API uses a deterministic local fallback so the UI remains playable.
