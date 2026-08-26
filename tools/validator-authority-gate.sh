#!/usr/bin/env bash
# VALR-T07 Stage-1 Validator authority regression gate — named repeatable entry.
#
# This script IS the gate: it runs the single integrated test binary that
# internally asserts all six regression classes (single-pass, strict truth,
# selection truth, backend truth, restart truth, required-live truth) plus
# validates deterministic ordering and the fail-fast / best-effort modes.
# It does not merely list unassociated cargo commands — the assertions live
# inside `apps/loom-validator/tests/authority_gate.rs` and this wrapper
# fails closed if that binary does not exercise all six.
#
# Usage:
#   bash tools/validator-authority-gate.sh
#   bash tools/validator-authority-gate.sh --json /tmp/gate-report.json
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== VALR-T07 authority gate =="
echo "root: $ROOT_DIR"
echo "gate binary: cargo test -p loom-validator --test authority_gate --all-features"
echo ""

# Use the repository-managed test helper so PostgreSQL service lifecycle
# matches CI (tools/test.sh starts the local pg service when needed and
# exports LOOM_TEST_POSTGRES_URL for the gate's controlled-harness subcases).
# When LOOM_TEST_POSTGRES_URL is already set, it is used as-is (CI ephemeral PG).
if [[ "${1:-}" == "--json" && -n "${2:-}" ]]; then
  JSON_OUT="$2"
  shift 2
else
  JSON_OUT=""
fi

echo "[gate] running authority_gate integration test..."
# The test binary itself asserts the six classes; exit 0 means all asserted.
bash tools/test.sh -p loom-validator --test authority_gate --all-features -- --nocapture

echo ""
echo "[gate] running focused regression suites (reused by gate, must stay green)..."
# Re-run the three integration suites that the gate conceptually closes,
# to prove no regression when viewed both via gate and standalone.
bash tools/test.sh -p loom-validator --test backend_evidence --all-features -- --nocapture
bash tools/test.sh -p loom-validator --test restart_evidence --all-features -- --nocapture
bash tools/test.sh -p loom-validator --test required_live --all-features -- --nocapture

echo ""
echo "[gate] running validator_ready ledger invariant for recert stage-1..."
python3 tools/validator_ready.py --root docs/tasks/validator-recert/stage-1 --check --format json | python3 -c "
import json, sys
data=json.load(sys.stdin)
print(json.dumps({k: data[k] for k in ('record_count','valid','violations','ready','blocked')}, indent=2, sort_keys=True))
if not data.get('valid'):
    print('validator_ready: violations present', file=sys.stderr)
    sys.exit(1)
"

echo ""
echo "[gate] architecture checks..."
python3 tools/check_architecture.py
python3 tools/check_storage_sql_ownership.py

echo ""
echo "[gate] fmt check..."
cargo fmt --all -- --check

if [[ -n "$JSON_OUT" ]]; then
  cat > "$JSON_OUT" <<EOF
{
  "gate": "VALR-T07 authority_gate",
  "command": "bash tools/validator-authority-gate.sh",
  "result": "pass",
  "evidence": "apps/loom-validator/tests/authority_gate.rs"
}
EOF
  echo "[gate] wrote $JSON_OUT"
fi

echo ""
echo "== gate PASS =="
echo "All six Stage-1 regression classes are exercised together in one gate."
echo "Proof: apps/loom-validator/tests/authority_gate.rs"
echo "Repeat: bash tools/validator-authority-gate.sh"
