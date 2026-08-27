---
task: VALR-T18
issue: 323
status: in_progress
depends_on: [314]
created_at: 2026-08-26
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T18 — Validate resumable Change Feed/SSE through formal client

Owner: T18 (#323) — `CV-038..CV-040`. Depends on T09 scaffold (#314). Parallel batch Stage-2 capability batch.

## Goal

Validate committed change-feed/SSE behavior through the formal Loom client surface, including resume/cursor semantics and disconnect recovery without turning the transport stream into a second source of World authority. Implement T08 rows CV-038..CV-040.

## Scenario Contract

- **CV-038:** a committed Event becomes observable through the formal change-feed/SSE client path with the expected identity/order.
- **CV-039:** resuming from a valid cursor continues from the documented boundary without losing committed events or manufacturing duplicates.
- **CV-040:** disconnect/reconnect recovery preserves authoritative history semantics; any transport duplicate/retry behavior must be distinguishable from duplicate World commits.

Follow T08 if exact cursor semantics are refined there.

## Formal Surface (Authoritative)

- `loom-api::SubscriptionService::subscribe(SubscriptionRequest::new / resume)` and `poll_change_feed` alias
- `loom-api::ChangeFeedCursor::after(target, EventSeq)` and `beginning`
- `loom-api::ChangeFeedPage { events, next_cursor, has_more }` and `SubscriptionResult::{Events, Resumed, Reconnect, Backpressure}`
- `loom_client::LoomClient::subscribe_http` via `LoomClient` HTTP/SSE (Last-Event-ID header, `text/event-stream`)
- Correlation via `HistoryService::list_events(EventQuery::all(target))`, `WorldService::create_world_from_template`, `ActionService::invoke`

No central registry edits, no internal event-table polling as substitute, no cursor redefinition, no unrelated CLI changes. If formal API does not define required cursor/resume semantics, escalate per Stop Conditions.

## Allowed Scope

- Dedicated change-feed/SSE suite module from T09: `apps/loom-validator/src/change_feed.rs`
- Dedicated integration tests and controlled HTTP fixtures: `apps/loom-validator/tests/change_feed.rs` (uses `tests/common::{InMemoryServer, PgServer}` real boundary)
- This task's ledger record `t18-change-feed.md`

## Forbidden Scope

- No central registry edits (T19): no `validator_registry` mutation for CV-038..040, no `src/registry.rs`/`lib.rs` central wiring.
- No internal `event-table` polling from production scenario code as substitute for SSE/client validation.
- Do not redefine cursor semantics (`ChangeFeedCursor::after` is authority).
- No unrelated CLI work.

## Implementation

### Production Module `src/change_feed.rs`

- Retains T09 ownership markers `SUITE="change_feed"`, `CV_RANGE="CV-038..CV-040"`, `CAPABILITY_AREA="change-feed"` and `owns_cv`.
- Exposes local suite registry: `descriptors() -> Vec<ScenarioDescriptor>` (3), `change_feed_registry()`, `register()`, `execute()` dispatcher.
- Constants `CV_038`, `CV_039`, `CV_040` with `CapabilityArea="change-feed"`, `supported_backends=[LoomClient, InMemory, PostgreSQL]`, prerequisites and architecture refs per T08.
- Helper `deterministic_world_template()` uses `validator.change-feed.t18` v1 with `neutral.counter@^0.1.0`.
- Deterministic IDs via `parse_id` (UUID suffix) for `EntityId`/`EventId` per scenario.
- `execute_cv038`: creates World, commits one `neutral.counter.seed` Event, correlates `HistoryService::list_events` authoritative history with `SubscriptionService::subscribe(SubscriptionRequest::new(target, 50))` → `SubscriptionResult::Events` containing same `EventId`/`EventSeq`, verifies ordering and `next_cursor == ChangeFeedCursor::after(target, committed_seq)` monotonic.
- `execute_cv039`: creates 5 events (seq 1..5), cursor after 5, then 2 events (6,7). First `subscribe(resume after 5)` returns `Events` with exactly 6,7 and `next_cursor after 7`; second `subscribe(resume after 7)` with no new events returns `Resumed(cursor after 7)`. When `BackendEvidence::PostgreSQL` with `ControlledBoundaryRestart`, performs `BackendContext::restart()` (preserve store, rebuild boundary) and re-validates both resumes and history 7 via formal client, proving durable cursor.
- `execute_cv040`: creates 3 events (seq 1..3), initial `subscribe(new)` returns 3 events with `next_cursor after 3`; simulates disconnect via `BackendContext::restart()` when `can_perform_boundary_restart()` else transport reconnect. Verifies `list_events` still exactly 3 (no second commit), `resume after 3` → `Resumed`, duplicate resume after 1 returns same 2 events (2,3) twice without creating new history, proving transport duplicate != world duplicate via `EventId` dedup. All observations via formal `LoomClient` surfaces.
- Evidence references include `validator:change-feed`, `backend:*`, `backend_evidence:*`, `restart_capability:*`, and `public-surface:loom-client::*` for subscription/history/action/world reads. Infra `unavailable` mapped to `ScenarioOutcome::Unavailable`, not `Pass`.
- No imports of `loom-storage`, `loom-runtime`, `loom-boundary`; no central registry mutation.

### Integration Tests `tests/change_feed.rs`

- Retains original scaffold disjoint test plus local registry check.
- Helpers `in_memory_context`, `pg_context` build real `InMemoryServer`/`PgServer` with `BackendContext::with_controlled_boundary_restart()` and deterministic scope.
- `cv038_passes_on_real_in_memory_via_formal_subscription`, `cv039_resume_passes_on_real_in_memory`, `cv040_disconnect_reconnect_preserves_history_on_real_in_memory` each exercise one CV against real InMemory HTTP boundary.
- `cv038_to_cv040_pass_on_live_postgres_with_controlled_restart` loops CV-038..040 against live PostgreSQL with controlled restart, asserting durable cursor/history for 039/040.
- `change_feed_scenarios_use_formal_client_not_event_table_polling` asserts source contains `SubscriptionService::subscribe`, `ChangeFeedCursor::after` and contains no `loom_storage`/`PgStorage`/`InMemoryStore`.

## Required Evidence (per Issue)

- committed event observed via formal stream/client: CV-038 passes `SubscriptionResult::Events` correlation.
- resume from known cursor: CV-039 passes resume after 5 → 6,7 and after 7 → Resumed.
- controlled disconnect + reconnect: CV-040 passes restart-preserved history 3 and duplicate page dedup.
- assertion World history contains exactly authoritative commits even if transport retried: CV-040 verifies `list_events` 3 before/after duplicate fetches, `EventId` dedup.
- PostgreSQL live path where T08 requires durable resume: CV-039 and CV-040 include controlled PostgreSQL restart branch (`BackendContext::restart()` on `PgServer` preserving `PgStorage`) with re-subscribe verification.

## Verification Evidence

- Replayed the T18 commit onto `origin/main` `b7696aae3bb978a48eb75650026fdc7bd16c2e98`; candidate HEAD: `4f8f86b6db8b589e192ab6ac153c0ef681d815a2` before this ledger-only evidence update.
- `cargo fmt --all -- --check` → PASS
- `cargo check -p loom-validator --all-targets` → PASS
- `cargo clippy -p loom-validator --all-targets -- -D warnings` → PASS
- `cargo test -p loom-validator --test change_feed -- --nocapture` → PASS (6 passed; 0 failed; 0 ignored; InMemory CV-038/039/040 plus live PostgreSQL CV-038..040 with controlled restart)
- `bash tools/test.sh -p loom-validator --all-targets` → PASS (153 unit tests and all loom-validator integration suites; PostgreSQL service prepared by the repository wrapper)
- `python3 tools/validator_ready.py --root docs/tasks/validator-recert --check --format json` → PASS (`valid: true`; T18 enumerated ready/in_progress)
- `python3 tools/check_architecture.py` → PASS
- `python3 tools/check_storage_sql_ownership.py` → PASS
- `git diff --check origin/main...HEAD` and three-file name/status boundary → PASS

## Acceptance

- [ ] CV-038..CV-040 match T08 (descriptors, preconditions, formal surfaces, expected results).
- [ ] Stream observations are correlated to committed World history through formal APIs (`HistoryService::list_events` vs `SubscriptionService::subscribe`).
- [ ] Resume/disconnect cases do not hide missed or duplicate authoritative commits (`EventId`/`EventSeq` dedup, `Resumed` vs `Events` boundary, `list_events` exact counts).
- [ ] Dedicated tests + fmt/check/clippy + CI pass; review complete.

## Stop Conditions

If cursor/resume semantics are not defined by current formal API contract, stop and escalate rather than encoding transport-specific policy as architecture. This implementation uses `ChangeFeedCursor::after`, `SubscriptionRequest::resume`, `SubscriptionResult::Events/Resumed` as defined in `crates/loom-api/src/lib.rs` and `crates/loom-client/src/lib.rs`; no new transport policy invented.

## Progress Log

- 2026-08-27 — Implemented `src/change_feed.rs` CV-038..040 via formal `loom-client`/`loom-api` (WorldService, ActionService, HistoryService, SubscriptionService) with ChangeFeedCursor/SubscriptionRequest semantics and controlled restart durability for PostgreSQL. Added `tests/change_feed.rs` InMemory/PostgreSQL integration harness with controlled `InMemoryServer`/`PgServer` restart, plus formal-surface negative check. Created ledger `t18-change-feed.md` as in_progress.
