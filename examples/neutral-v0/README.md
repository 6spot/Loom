# Neutral V0 Examples — Loom

Deterministic, finance/social/game-free examples that exercise the complete V0 public surface through **only** `loom-api` / `loom-client` / `loom-cli` and Template descriptors. No direct SQL or `loom-storage` mutation is used in user-facing setup.

- **Extension surface only:** all semantics live in `capabilities/loom-neutral` (counter + observer, relationship, blob reference, semantic index) — never in `loom-runtime`, `loom-core`, `loom-protocol` or `loom-api`.
- **Two Template revisions visibly differ:** `templates/revision-1.json` (`counter` profile, one bootstrap) vs `templates/revision-2.json` (`observer` profile, two bootstraps, observer dependency on counter). A World created from revision 1 never mutates when revision 2 is later used for a new World — future-World-only change. An observer Action installed globally is `Unavailable` for revision-1 Worlds (installed-but-disabled).
- **Concepts covered:** Entity/Relationship/Facet (`neutral.counter.value`, `neutral.blob.reference`, `neutral.link.membership`), Action/Event (`seed`/`increment`/`observe`/`link.create`/`blob.attach`), cross-Capability dependency (`observer → counter`), Reaction/Work (`incremented → increment_work` chains), semantic retrieval (`neutral.counter.semantic` via `SemanticProjectionStore` registration/rebuild/query, see below), blob references (immutable `InMemoryBlobStore`/`LocalBlobStore` hash stored in a Facet), deterministic Agency (`deterministic.fake` executor, no vendor credentials).
- **Deterministic IDs/world time:** all example identities use fixed UUIDs and `WorldInstant` values (11 and 22) so JSON and CLI outputs are script-stable. Only scheduler/lease `PlatformTime` uses wall-clock.

## Clean-machine setup

Build the exact CLI product once from the repository root:

```sh
cargo build -p loom-cli
# binary: ./target/debug/loom-cli  (Cargo package/target name is `loom-cli`)
# Clap help shows `loom` as display name only: `cargo run -p loom-cli -- --help`
```

All commands below use the built product. Either use the binary directly or the `cargo run` wrapper:

```sh
LOOM_CLI="./target/debug/loom-cli"
# or
LOOM_CLI="cargo run -q -p loom-cli --"
```

## Quickstart via CLI (no vendor credentials)

```sh
# 1. Catalog discovery (global vs per-World)
$LOOM_CLI catalog
$LOOM_CLI catalog --world-id 00000000-0000-0000-0000-000000005110

# 2. World creation from Template (public birth path)
$LOOM_CLI world create --template-file examples/neutral-v0/templates/revision-1.json
$LOOM_CLI world create --template-file examples/neutral-v0/templates/revision-2.json
# or: $LOOM_CLI world create --template-json '{"id":"neutral.world","revision":1,...}'

# 3. Action / state (Entity + Facet)
ENTITY=00000000-0000-0000-0000-000000005101
OTHER_ENTITY=00000000-0000-0000-0000-000000005102
EVENT1=00000000-0000-0000-0000-000000005170
WORLD=... TIMELINE=... # from step 2 output
$LOOM_CLI action invoke --world $WORLD --timeline $TIMELINE --action neutral.counter.increment --input "{\"event_id\":\"$EVENT1\",\"entity_id\":\"$ENTITY\",\"amount\":1}"
$LOOM_CLI facet get --world $WORLD --timeline $TIMELINE --owner $ENTITY --facet-type neutral.counter.value

# 4. Relationship (neutral link) — demonstrates Entity/Relationship distinction
# First create the second participant as a real Entity via the public Action (no direct storage/SQL):
$LOOM_CLI action invoke --world $WORLD --timeline $TIMELINE --action neutral.counter.seed --input "{\"event_id\":\"00000000-0000-0000-0000-000000005183\",\"entity_id\":\"$OTHER_ENTITY\",\"value\":7}"
REL=00000000-0000-0000-0000-000000006001
$LOOM_CLI action invoke --world $WORLD --timeline $TIMELINE --action neutral.link.create --input "{\"event_id\":\"00000000-0000-0000-0000-000000005184\",\"relationship_id\":\"$REL\",\"left_entity\":\"$ENTITY\",\"right_entity\":\"$OTHER_ENTITY\"}"
$LOOM_CLI trajectory relationship --world $WORLD --timeline $TIMELINE --relationship-id $REL

# 5. Blob reference (immutable blob hash retained in Facet)
# Fabricate a deterministic local blob hash (example: use CLI's JSON input; real blob bytes flow through the BlobStore port in server mode)
$LOOM_CLI action invoke --world $WORLD --timeline $TIMELINE --action neutral.blob.attach --input "{\"event_id\":\"00000000-0000-0000-0000-000000005172\",\"entity_id\":\"$ENTITY\",\"hash\":\"sha256:example\",\"media_type\":\"text/plain\"}"
$LOOM_CLI facet get --world $WORLD --timeline $TIMELINE --owner $ENTITY --facet-type neutral.blob.reference

# 6. History / causality / trajectory
$LOOM_CLI history events --world $WORLD --timeline $TIMELINE
$LOOM_CLI history event --timeline $TIMELINE --event-id $EVENT1
$LOOM_CLI history causes --timeline $TIMELINE --event-id $EVENT1
$LOOM_CLI history walk --timeline $TIMELINE --event-id $EVENT1 --direction causes
$LOOM_CLI trajectory entity --world $WORLD --timeline $TIMELINE --entity-id $ENTITY

# 7. Semantic retrieval (real projection, not just catalog)
# Catalog discovery:
$LOOM_CLI catalog --world-id $WORLD | jq .semantic_indexes
# Deterministic retrieval is exercised by `tests/loom-composition/neutral_v0_workflows.rs:neutral_v0_public_workflows_via_api`
# via the public `SemanticProjectionStore` Runtime boundary: it registers
# `SemanticProjectionRegistration` for `neutral.counter.semantic` (matching the
# catalog's `SemanticIndexDefinition`), rebuilds deterministic
# `SemanticProjectionRow`s from fixed committed `EventRef`/version, and queries
# with a bounded `SemanticProjectionQuery` asserting hit ordering/source.

# 8. Ingress + Change Feed (durable platform input, resumable feed)
$LOOM_CLI ingress submit --world $WORLD --timeline $TIMELINE --action neutral.counter.increment --input "{\"event_id\":\"00000000-0000-0000-0000-000000005173\",\"entity_id\":\"$ENTITY\",\"amount\":1}" --ingress-id ingress-1
$LOOM_CLI ingress status --ingress-id ingress-1
$LOOM_CLI feed subscribe --world $WORLD --timeline $TIMELINE --limit 10

# 9. Timeline fork & replay (branch isolation, deterministic replay)
$LOOM_CLI timeline fork --world $WORLD --timeline $TIMELINE
$LOOM_CLI timeline fork --world $WORLD --timeline $TIMELINE --source-version 1:1
$LOOM_CLI history events --world $WORLD --timeline forked-timeline-id

# 10. Admin — Runtime Revision / Session / Agency / World Time (requires --admin-token)
$LOOM_CLI admin revision list
$LOOM_CLI admin revision get --revision-id neutral-fixtures-r1
$LOOM_CLI admin session list
$LOOM_CLI admin session for-event --timeline $TIMELINE --event-id $EVENT1
$LOOM_CLI admin timeline status --world $WORLD --timeline $TIMELINE
$LOOM_CLI admin agency schedule-wake --world $WORLD --timeline $TIMELINE --work-id 00000000-0000-0000-0000-000000007001 --agent $ENTITY --cognition deterministic.fake --payload '{}'
$LOOM_CLI admin world-time advance --world $WORLD --timeline $TIMELINE --expected-head-seq 3 --expected-state-rev 3 --current 11 --next 22
```

All JSON inputs/outputs are `loom-api` DTOs; local validation is UX-only, the server remains authority (`ApiErrorCode → exit code 10–16`).

## Restart / Replay / Fork — how the examples survive

- **Restart:** `loom-server` persists Timeline Logical State, Event history and World Runtime Binding in `loom-storage` (`PgStorage`) via Runtime-owned ports. A process restart constructs a fresh `Runtime<PgStorage>` over the same store; the fixture identities above read back identical history, binding and provenance. See `tests/loom-composition/neutral_v0_workflows.rs::neutral_v0_restart_keeps_binding_and_history`.
- **Replay:** `LogicalReplayEngine` / `replay_timeline` reconstructs `TimelineVersion`, `WorldInstant`, logical Work and Chronology Budget from committed Events without re-running resolvers. Forked Timelines replay independently.
- **Fork:** `loom-cli timeline fork` clones branch-local Pending Work with a fresh `WorkId` while preserving semantic `(target, due, order)`. `Relationship` and `Facet` trajectories remain isolated per Timeline.

## Deterministic Agency without vendor credentials

`loom-agency` ships `DeterministicCognitiveExecutor` (`deterministic.fake`). The neutral example schedules an Agency Wake via `cargo run -p loom-cli -- admin agency schedule-wake` and drives it with the fake (no network, no API key). A semantic `Decision::Act` is routed through normal `ActionService` authority; a `NoAction` is a determined terminal outcome. See `tests/loom-composition/neutral_v0_workflows.rs::neutral_v0_agency_deterministic_without_vendor_credentials`.

## What is intentionally deferred

Real vendor LLM/provider adapters remain non-blocking/deferred; the supported V0 path is the deterministic fake. `examples/neutral-v0` contains no `UPDATE timeline SET ...`, no direct `loom_storage` SQL fixture mutation and no `loom-runtime` domain hard-coding.
