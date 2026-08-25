# Neutral V0 Workflows — step-by-step

Each step uses only public `loom-api` DTOs via `loom-cli` (or `loom-client`). Replace `$WORLD`/`$TIMELINE` with the `target` returned by `loom world create`.

## 1. Inspect catalog and binding
```sh
loom catalog | jq '.capabilities[] | .id'
loom catalog --world-id $WORLD | jq '{capabilities: [.capabilities[] | .id], bindings: .}'
```

## 2. Create two Worlds from different Templates (future-World-only)
```sh
loom world create --template-file examples/neutral-v0/templates/revision-1.json > /tmp/w1.json
loom world create --template-file examples/neutral-v0/templates/revision-2.json > /tmp/w2.json
jq . /tmp/w1.json  # contains neutral.counter only
jq . /tmp/w2.json  # contains neutral.counter + neutral.observer
loom history events --world $(jq -r .target.world_id /tmp/w1.json) --timeline $(jq -r .target.timeline_id /tmp/w1.json)
loom history events --world $(jq -r .target.world_id /tmp/w2.json) --timeline $(jq -r .target.timeline_id /tmp/w2.json)
```

## 3. Prove installed-but-disabled
```sh
# observer is globally installed but disabled for a revision-1 World:
loom action invoke --world $W1_WORLD --timeline $W1_TIMELINE --action neutral.observer.observe \
  --input '{"event_id":"00000000-0000-0000-0000-000000005140","entity_id":"00000000-0000-0000-0000-000000005101"}'
# → exits 13, {"code":"unavailable","message":"... not enabled for target World"}
```

## 4. Run the full neutral walk (Entity/Facet, Relationship, Reaction/Work, blob ref)
```sh
. examples/neutral-v0/workflows/walk.sh $WORLD $TIMELINE
cat examples/neutral-v0/workflows/walk.sh
```

## 5. Deterministic Agency walk (no vendor keys)
```sh
. examples/neutral-v0/workflows/agency.sh $WORLD $TIMELINE
```

## 6. Replay / fork validation (application-level scripts)
`cargo test -p loom-composition-tests --test neutral_v0_workflows -- --nocapture` exercises the same workflows through `loom-runtime` + `loom-storage::InMemoryStore` and `InMemoryBlobStore`, asserting that history, binding and agency outcomes survive restart, replay and fork without SQL mutation.
