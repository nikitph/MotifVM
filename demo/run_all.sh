#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

make test
make demo
make adversarial
make eval

rm -rf demo/audit_packs
mkdir -p demo/audit_packs
for case_dir in .motifvm/demo_outputs/*; do
  [ -d "$case_dir/audit_pack" ] || continue
  cp -R "$case_dir/audit_pack" "demo/audit_packs/$(basename "$case_dir")"
done

echo "All cases passed."
echo "Open demo/graph_explorer/index.html to inspect exported state.json files."
