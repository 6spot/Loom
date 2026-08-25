#!/usr/bin/env bash
set -euo pipefail
WORLD=${1:?world id}
TIMELINE=${2:?timeline id}
ENTITY=00000000-0000-0000-0000-000000005101
OTHER_ENTITY=00000000-0000-0000-0000-000000005102
REL=00000000-0000-0000-0000-000000006001
echo "== facet get (counter) =="
loom facet get --world "$WORLD" --timeline "$TIMELINE" --owner "$ENTITY" --facet-type neutral.counter.value || true
echo "== action increment =="
loom action invoke --world "$WORLD" --timeline "$TIMELINE" --action neutral.counter.increment --input "{\"event_id\":\"00000000-0000-0000-0000-000000005180\",\"entity_id\":\"$ENTITY\",\"amount\":1}"
echo "== relationship create =="
loom action invoke --world "$WORLD" --timeline "$TIMELINE" --action neutral.link.create --input "{\"event_id\":\"00000000-0000-0000-0000-000000005181\",\"relationship_id\":\"$REL\",\"left_entity\":\"$ENTITY\",\"right_entity\":\"$OTHER_ENTITY\"}" || true
echo "== blob attach (reference retained as facet) =="
loom action invoke --world "$WORLD" --timeline "$TIMELINE" --action neutral.blob.attach --input "{\"event_id\":\"00000000-0000-0000-0000-000000005182\",\"entity_id\":\"$ENTITY\",\"hash\":\"sha256:neutral-blob-demo\",\"media_type\":\"text/plain\"}"
loom facet get --world "$WORLD" --timeline "$TIMELINE" --owner "$ENTITY" --facet-type neutral.blob.reference
echo "== history =="
loom history events --world "$WORLD" --timeline "$TIMELINE" | head -c 2000
echo "== catalog semantic_indexes =="
loom catalog --world-id "$WORLD" | jq .semantic_indexes
