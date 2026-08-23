#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${LOOM_TEST_ENV_FILE:-.env.test.local}"

# Reuse the repository-managed PostgreSQL service when it already exists;
# Docker Compose only creates/pulls what is missing.
bash tools/postgres-test.sh up >/dev/null

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-loom}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-loom}"
POSTGRES_DB="${POSTGRES_DB:-loom_control}"
POSTGRES_PORT="${POSTGRES_PORT:-15432}"

export LOOM_TEST_POSTGRES_URL="${LOOM_TEST_POSTGRES_URL:-postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}}"

exec cargo test "$@"
