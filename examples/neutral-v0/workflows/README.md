# Neutral V0 Workflows — step-by-step

Each step uses only public `loom-api` DTOs via the real `loom-cli` product. Build once:

```sh
cargo build -p loom-cli
# or use the wrapper below without pre-building
```

Set `LOOM_CLI` to the actual product:

```sh
LOOM_CLI="./target/debug/loom-cli"
# or
LOOM_CLI="cargo run -q -p loom-cli --"
```

Replace `$WORLD`/`$TIMELINE` with the `target` returned by `loom-cli world create`.

## 1. Inspect catalog and binding
```sh
$LOOM_CLI catalog | jq '.capabilities[] | .id'
$LOOM_CLI catalog --world-id $WORLD | jq '{capabilities: [.capabilities[] | .id], bindings: .}'
```

## 2. Create two Worlds from different Templates (future-World-only)
```sh
$LOOM_CLI world create --template-file examples/neutral-v0/templates/revision-1.json > /tmp/w1.json
$LOOM_CLI world create --template-file examples/neutral-v0/templates/revision-2.json > /tmp/w2.json
jq . /tmp/w1.json  # contains neutral.counter only
jq . /tmp/w2.json  # contains neutral.counter + neutral.observer
$LOOM_CLI history events --world $(jq -r .target.world_id /tmp/w1.json) --timeline $(jq -r .target.timeline_id /tmp/w1.json)
$LOOM_CLI history events --world $(jq -r .target.world_id /tmp/w2.json) --timeline $(jq -r .target.timeline_id /tmp/w2.json)
```

## 3. Prove installed-but-disabled
```sh
# observer is globally installed but disabled for a revision-1 World:
$LOOM_CLI action invoke --world $W1_WORLD --timeline $W1_TIMELINE --action neutral.observer.observe \
  --input '{"event_id":"00000000-0000-0000-0000-000000005140","entity_id":"00000000-0000-0000-0000-000000005101"}'
# → exits 13, {"code":"unavailable","message":"... not enabled for target World"}
```

## 4. Run the full neutral walk (Entity/Facet, Relationship, Reaction/Work, blob ref, semantic retrieval)
```sh
LOOM_CLI="$LOOM_CLI" examples/neutral-v0/workflows/walk.sh $WORLD $TIMELINE
cat examples/neutral-v0/workflows/walk.sh
# walk.sh now seeds the second participant via public `neutral.counter.seed`
# (event 00000000-0000-0000-0000-000000005183) before `neutral.link.create`
# (event 00000000-0000-0000-0000-000000005184) and does not swallow errors.
# Semantic retrieval catalog discovery is followed by a real
# SemanticProjectionStore rebuild/query exercised deterministically in
# `tests/loom-composition/neutral_v0_workflows.rs`.
```

## 5. Deterministic Agency walk (no vendor keys)
```sh
LOOM_CLI="$LOOM_CLI" examples/neutral-v0/workflows/agency.sh $WORLD $TIMELINE
```

## 6. Replay / fork validation (application-level scripts)
`cargo test -p loom-composition-tests --test neutral_v0_workflows -- --nocapture` exercises the same workflows through `loom-runtime` + `loom-storage::InMemoryStore` and `InMemoryBlobStore`, asserting that history, binding and agency outcomes survive restart, replay and fork without SQL mutation. Semantic retrieval is validated via `SemanticProjectionStore` (registration/rebuild/query) with bounded limits and ordered-hit assertions.
