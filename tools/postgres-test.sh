#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${LOOM_TEST_ENV_FILE:-.env.test.local}"
COMPOSE_FILE="compose.test-db.yaml"
COMPOSE_PROJECT="${LOOM_TEST_COMPOSE_PROJECT:-loom}"

compose() {
  if [[ -f "$ENV_FILE" ]]; then
    docker compose --project-name "$COMPOSE_PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  else
    docker compose --project-name "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" "$@"
  fi
}

case "${1:-up}" in
  up)
    compose up -d --wait --wait-timeout 60
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
