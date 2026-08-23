#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${LOOM_TEST_ENV_FILE:-.env.test.local}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "$ENV_FILE does not exist." >&2
  echo "Initialize the local PostgreSQL test service first:" >&2
  echo "  bash tools/postgres-test.sh up" >&2
  exit 2
fi

# Keep the repository-owned local PostgreSQL service available before running
# integration tests. `docker compose up -d` is idempotent when it is already up.
bash tools/postgres-test.sh up >/dev/null

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${LOOM_TEST_POSTGRES_URL:?LOOM_TEST_POSTGRES_URL must be set in $ENV_FILE}"
export LOOM_REQUIRE_POSTGRES_TESTS="${LOOM_REQUIRE_POSTGRES_TESTS:-1}"

exec cargo test "$@"
