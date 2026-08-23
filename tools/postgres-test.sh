#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="compose.test-db.yaml"
COMPOSE_PROJECT="${LOOM_TEST_COMPOSE_PROJECT:-loom}"
LOCK_FILE="${LOOM_TEST_POSTGRES_LOCK_FILE:-${TMPDIR:-/tmp}/loom-postgres-test.lock}"

compose() {
  docker compose --project-name "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" "$@"
}

lock_startup() {
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    flock 9
  fi
}

case "${1:-up}" in
  up)
    lock_startup
    compose up -d --wait --wait-timeout 60
    # Older local volumes may have been initialized when the repository used a
    # generated password. Local socket authentication inside the container is
    # trusted, so reconcile the test-only role to today's fixed credential.
    compose exec -T postgres-test \
      psql -v ON_ERROR_STOP=1 -U loom -d postgres \
      -c "ALTER ROLE loom WITH PASSWORD 'loom';" >/dev/null
    compose ps
    ;;
  down)
    compose down
    ;;
  status)
    compose ps
    ;;
  logs)
    compose logs -f postgres-test
    ;;
  *)
    echo "Usage: bash tools/postgres-test.sh [up|down|status|logs]" >&2
    exit 2
    ;;
esac
