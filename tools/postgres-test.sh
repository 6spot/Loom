#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${LOOM_TEST_ENV_FILE:-.env.test.local}"
COMPOSE_FILE="compose.test-db.yaml"

init_env() {
  if [[ -f "$ENV_FILE" ]]; then
    return
  fi

  local password
  password="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"

  cat >"$ENV_FILE" <<EOF
POSTGRES_USER=loom
POSTGRES_PASSWORD=${password}
POSTGRES_DB=loom_control
POSTGRES_PORT=15432
LOOM_TEST_POSTGRES_URL=postgresql://loom:${password}@127.0.0.1:15432/loom_control
LOOM_REQUIRE_POSTGRES_TESTS=1
EOF
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE with a generated local test password."
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

case "${1:-up}" in
  init)
    init_env
    ;;
  up)
    init_env
    compose up -d --wait --wait-timeout 60
    compose ps
    ;;
  down)
    if [[ ! -f "$ENV_FILE" ]]; then
      echo "$ENV_FILE does not exist; there is no configured local test database to stop." >&2
      exit 2
    fi
    compose down
    ;;
  status)
    if [[ ! -f "$ENV_FILE" ]]; then
      echo "$ENV_FILE does not exist. Run: bash tools/postgres-test.sh up" >&2
      exit 2
    fi
    compose ps
    ;;
  logs)
    if [[ ! -f "$ENV_FILE" ]]; then
      echo "$ENV_FILE does not exist. Run: bash tools/postgres-test.sh up" >&2
      exit 2
    fi
    compose logs -f postgres-test
    ;;
  *)
    echo "Usage: bash tools/postgres-test.sh [init|up|down|status|logs]" >&2
    exit 2
    ;;
esac
