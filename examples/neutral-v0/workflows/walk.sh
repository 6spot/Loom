#!/usr/bin/env bash
set -euo pipefail
WORLD=${1:?world id}
TIMELINE=${2:?timeline id}
ENTITY=00000000-0000-0000-0000-000000005101
OTHER_ENTITY=00000000-0000-0000-0000-000000005102
REL=00000000-0000-0000-0000-000000006001
LOOM_CLI="${LOOM_CLI:-cargo run -q -p loom-cli --}"
echo "== facet get (counter) =="
$LOOM_CLI facet get --world "$WORLD" --timeline "$TIMELINE" --owner "$ENTITY" --facet-type neutral.counter.value
echo "== action increment =="
$LOOM_CLI action invoke --world "$WORLD" --timeline "$TIMELINE" --action neutral.counter.increment --input "{\"event_id\":\"00000000-0000-0000-0000-000000005180\",\"entity_id\":\"$ENTITY\",\"amount\":1}"
echo "== seed second participant (public Action, no direct storage/SQL) =="
$LOOM_CLI action invoke --world "$WORLD" --timeline "$TIMELINE" --action neutral.counter.seed --input "{\"event_id\":\"00000000-0000-0000-0000-000000005183\",\"entity_id\":\"$OTHER_ENTITY\",\"value\":7}"
echo "== relationship create (deterministic IDs, error not swallowed) =="
$LOOM_CLI action invoke --world "$WORLD" --timeline "$TIMELINE" --action neutral.link.create --input "{\"event_id\":\"00000000-0000-0000-0000-000000005184\",\"relationship_id\":\"$REL\",\"left_entity\":\"$ENTITY\",\"right_entity\":\"$OTHER_ENTITY\"}"
echo "== blob attach (reference retained as facet) =="
$LOOM_CLI action invoke --world "$WORLD" --timeline "$TIMELINE" --action neutral.blob.attach --input "{\"event_id\":\"00000000-0000-0000-0000-000000005182\",\"entity_id\":\"$ENTITY\",\"hash\":\"sha256:neutral-blob-demo\",\"media_type\":\"text/plain\"}"
$LOOM_CLI facet get --world "$WORLD" --timeline "$TIMELINE" --owner "$ENTITY" --facet-type neutral.blob.reference
echo "== history =="
$LOOM_CLI history events --world "$WORLD" --timeline "$TIMELINE" | head -c 2000
echo "== catalog semantic_indexes (discovery) =="
$LOOM_CLI catalog --world-id "$WORLD" | jq .semantic_indexes
echo "== semantic retrieval (real projection query is exercised by neutral_v0_workflows test via SemanticProjectionStore) =="
echo "see tests/loom-composition/neutral_v0_workflows.rs for deterministic SemanticProjectionRegistration/rebuild/query"
