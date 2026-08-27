#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
DEFAULT_POSTGRES_URL="postgresql://loom:loom@127.0.0.1:15432/loom_control"
export LOOM_TEST_POSTGRES_URL="${LOOM_TEST_POSTGRES_URL:-$DEFAULT_POSTGRES_URL}"
export LOOM_T20_REPORT_PATH="${LOOM_T20_REPORT_PATH:-$ROOT_DIR/target/validator/t20-pg18-live-gate.json}"
if [[ "$LOOM_TEST_POSTGRES_URL" == "$DEFAULT_POSTGRES_URL" ]]; then
  bash tools/postgres-test.sh up
fi

# The Rust integration target invokes each frozen row's production executor
# and serializes structured ScenarioResult/Finding values. Cargo's exit status
# is only the test runner result; it never manufactures matrix evidence.
exec cargo test -p loom-validator --test postgres_live_gate -- --nocapture --test-threads=1
