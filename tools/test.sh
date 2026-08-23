#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Reuse the repository-managed PostgreSQL service when it already exists;
# Docker Compose only creates/pulls what is missing and waits for health.
bash tools/postgres-test.sh up >/dev/null

export LOOM_TEST_POSTGRES_URL="${LOOM_TEST_POSTGRES_URL:-postgresql://loom:loom@127.0.0.1:15432/loom_control}"

exec cargo test "$@"
