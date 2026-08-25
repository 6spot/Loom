#!/usr/bin/env bash
set -euo pipefail
WORLD=${1:?world id}
TIMELINE=${2:?timeline id}
ENTITY=00000000-0000-0000-0000-000000005101
WORK=00000000-0000-0000-0000-000000007001
echo "== schedule deterministic agency wake (no vendor credentials) =="
# deterministic.fake is the supported V0 example; no LLM key needed
loom admin agency schedule-wake --world "$WORLD" --timeline "$TIMELINE" --work-id "$WORK" --agent "$ENTITY" --cognition deterministic.fake --payload '{"goal":"neutral-demo"}'
echo "== timeline status shows wake =="
loom admin timeline status --world "$WORLD" --timeline "$TIMELINE"
