# Neutral V0 Examples — Loom

Deterministic, finance/social/game-free examples that exercise the complete V0 public surface through **only** `loom-api` / `loom-client` / `loom-cli` and Template descriptors. No direct SQL or `loom-storage` mutation is used in user-facing setup.

- **Extension surface only:** all semantics live in `capabilities/loom-neutral` (counter + observer, relationship, blob reference, semantic index) — never in `loom-runtime`, `loom-core`, `loom-protocol` or `loom-api`.
- **Two Template revisions visibly differ:** `templates/revision-1.json` (`counter` profile, one bootstrap) vs `templates/revision-2.json` (`observer` profile, two bootstraps, observer dependency on counter). A World created from revision 1 never mutates when revision 2 is later used for a new World — future-World-only change. An observer Action installed globally is `Unavailable` for revision-1 Worlds (installed-but-disabled).
- **Concepts covered:** Entity/Relationship/Facet (`neutral.counter.value`, `neutral.blob.reference`, `neutral.link.membership`), Action/Event (`seed`/`increment`/`observe`/`link.create`/`blob.attach`), cross-Capability dependency (`observer → counter`), Reaction/Work (`incremented → increment_work` chains), semantic retrieval slot (`neutral.counter.semantic` via catalog), blob references (immutable `InMemoryBlobStore`/`LocalBlobStore` hash stored in a Facet), deterministic Agency (`deterministic.fake` executor, no vendor credentials).
- **Deterministic IDs/world time:** all example identities use fixed UUIDs and `WorldInstant` values (11 and 22) so JSON and CLI outputs are script-stable. Only scheduler/lease `PlatformTime` uses wall-clock.

## Quickstart via CLI (no vendor credentials)

```sh
# 1. Catalog discovery (global vs per-World)
loom catalog
loom catalog --world-id 00000000-0000-0000-0000-000000005110

# 2. World creation from Template (public birth path)
loom world create --template-file examples/neutral-v0/templates/revision-1.json
loom world create --template-file examples/neutral-v0/templates/revision-2.json
# or: loom world create --template-json '{"id":"neutral.world","revision":1,...}'

# 3. Action / state (Entity + Facet)
ENTITY=00000000-0000-0000-0000-000000005101
EVENT1=00000000-0000-0000-0000-000000005170
WORLD=... TIMELINE=... # from step 2 output
loom action invoke --world $WORLD --timeline $TIMELINE --action neutral.counter.increment --input "{\"event_id\":\"$EVENT1\",\"entity_id\":\"$ENTITY\",\"amount\":1}"
loom facet get --world $WORLD --timeline $TIMELINE --owner $ENTITY --facet-type neutral.counter.value

# 4. Relationship (neutral link) — demonstrates Entity/Relationship distinction
REL=00000000-0000-0000-0000-000000006001
LEFT=00000000-0000-0000-0000-000000005101
RIGHT=00000000-0000-0000-0000-000000005102
loom action invoke --world $WORLD --timeline $TIMELINE --action neutral.link.create --input "{\"event_id\":\"00000000-0000-0000-0000-000000005171\",\"relationship_id\":\"$REL\",\"left_entity\":\"$LEFT\",\"right_entity\":\"$RIGHT\"}"
loom trajectory relationship --world $WORLD --timeline $TIMELINE --relationship-id $REL

# 5. Blob reference (immutable blob hash retained in Facet)
# Fabricate a deterministic local blob hash (example: use CLI's JSON input; real blob bytes flow through the BlobStore port in server mode)
loom action invoke --world $WORLD --timeline $TIMELINE --action neutral.blob.attach --input "{\"event_id\":\"00000000-0000-0000-0000-000000005172\",\"entity_id\":\"$ENTITY\",\"hash\":\"sha256:example\",\"media_type\":\"text/plain\"}"
loom facet get --world $WORLD --timeline $TIMELINE --owner $ENTITY --facet-type neutral.blob.reference

# 6. History / causality / trajectory
loom history events --world $WORLD --timeline $TIMELINE
loom history event --timeline $TIMELINE --event-id $EVENT1
loom history causes --timeline $TIMELINE --event-id $EVENT1
loom history walk --timeline $TIMELINE --event-id $EVENT1 --direction causes
loom trajectory entity --world $WORLD --timeline $TIMELINE --entity-id $ENTITY

# 7. Semantic retrieval slot (catalog shows neutral.counter.semantic)
loom catalog --world-id $WORLD | jq .semantic_indexes

# 8. Ingress + Change Feed (durable platform input, resumable feed)
loom ingress submit --world $WORLD --timeline $TIMELINE --action neutral.counter.increment --input "{\"event_id\":\"00000000-0000-0000-0000-000000005173\",\"entity_id\":\"$ENTITY\",\"amount\":1}" --ingress-id ingress-1
loom ingress status --ingress-id ingress-1
loom feed subscribe --world $WORLD --timeline $TIMELINE --limit 10

# 9. Timeline fork & replay (branch isolation, deterministic replay)
loom timeline fork --world $WORLD --timeline $TIMELINE
loom timeline fork --world $WORLD --timeline $TIMELINE --source-version 1:1
loom history events --world $WORLD --timeline forked-timeline-id

# 10. Admin — Runtime Revision / Session / Agency / World Time (requires --admin-token)
loom admin revision list
loom admin revision get --revision-id neutral-fixtures-r1
loom admin session list
loom admin session for-event --timeline $TIMELINE --event-id $EVENT1
loom admin timeline status --world $WORLD --timeline $TIMELINE
loom admin agency schedule-wake --world $WORLD --timeline $TIMELINE --work-id 00000000-0000-0000-0000-000000007001 --agent $ENTITY --cognition deterministic.fake --payload '{}'
loom admin world-time advance --world $WORLD --timeline $TIMELINE --expected-head-seq 3 --expected-state-rev 3 --current 11 --next 22
```

All JSON inputs/outputs are `loom-api` DTOs; local validation is UX-only, the server remains authority (`ApiErrorCode → exit code 10–16`).

## Restart / Replay / Fork — how the examples survive

- **Restart:** `loom-server` persists Timeline Logical State, Event history and World Runtime Binding in `loom-storage` (`PgStorage`) via Runtime-owned ports. A process restart constructs a fresh `Runtime<PgStorage>` over the same store; the fixture identities above read back identical history, binding and provenance. See `tests/loom-composition/neutral_v0_workflows.rs::neutral_v0_restart_keeps_binding_and_history`.
- **Replay:** `LogicalReplayEngine` / `replay_timeline` reconstructs `TimelineVersion`, `WorldInstant`, logical Work and Chronology Budget from committed Events without re-running resolvers. Forked Timelines replay independently.
- **Fork:** `loom timeline fork` clones branch-local Pending Work with a fresh `WorkId` while preserving semantic `(target, due, order)`. `Relationship` and `Facet` trajectories remain isolated per Timeline.

## Deterministic Agency without vendor credentials

`loom-agency` ships `DeterministicCognitiveExecutor` (`deterministic.fake`). The neutral example schedules an Agency Wake via `loom admin agency schedule-wake` and drives it with the fake (no network, no API key). A semantic `Decision::Act` is routed through normal `ActionService` authority; a `NoAction` is a determined terminal outcome. See `tests/loom-composition/neutral_v0_workflows.rs::neutral_v0_agency_deterministic_without_vendor_credentials`.

## What is intentionally deferred

Real vendor LLM/provider adapters remain non-blocking/deferred; the supported V0 path is the deterministic fake. `examples/neutral-v0` contains no `UPDATE timeline SET ...`, no direct `loom_storage` SQL fixture mutation and no `loom-runtime` domain hard-coding.
