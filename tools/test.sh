#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${LOOM_TEST_ENV_FILE:-.env.test.local}"

# Ensure the repository-managed PostgreSQL test service exists and is running.
# On first use, postgres-test.sh also creates the local ignored env file.
bash tools/postgres-test.sh up >/dev/null

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${LOOM_TEST_POSTGRES_URL:?LOOM_TEST_POSTGRES_URL must be set in $ENV_FILE}"
export LOOM_REQUIRE_POSTGRES_TESTS="${LOOM_REQUIRE_POSTGRES_TESTS:-1}"

exec cargo test "$@"
