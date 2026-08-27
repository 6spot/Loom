---
task: VALR-T13
issue: 318
status: in_progress
depends_on: [314]
created_at: 2026-08-27
started_at: 2026-08-27
completed_at:
completion_pr:
merge_sha:
---

# VALR-T13 — Validate World Time + quiescence + Chronology + Reaction atomicity

## Scope and frozen matrix mapping

This record owns T08 rows CV-021..CV-024. The production scenarios are local
to `apps/loom-validator/src/world_time.rs`, and the dedicated integration
coverage is local to `apps/loom-validator/tests/world_time.rs`. Central
registration remains reserved for T19.

| CV | Public observation | Evidence |
| --- | --- | --- |
| CV-021 | `AdminService::advance_world_time` advances fixed `WorldInstant(T10)` to `T20` through Timeline CAS; `inspect_timeline` confirms the new version/time and `HistoryService::list_events` confirms no fake Event. | InMemory, live PostgreSQL |
| CV-022 | `neutral.counter.seed` followed by `neutral.counter.increment` uses the public semantic reaction path to produce semantically due Pending Work at `T20`; `AdminService::advance_world_time` is rejected by the quiescence barrier, and `AdminService::timeline_logical_status`/`TimelineService::inspect_timeline` confirm logical status/time/version remain unchanged. | InMemory, live PostgreSQL |
| CV-023 | `HistoryService::list_events` and paging, `TimelineService::inspect_timeline`, `AdminService::timeline_logical_status`, and `QueryService::get_facet` are compared before/after controlled boundary restart using the new client returned by the restart. | InMemory, live PostgreSQL, controlled restart |
| CV-024 | `ActionService::invoke` for `neutral.counter.increment` exposes the triggering committed Event and reaction Pending Work at the same TimelineVersion; both are compared after controlled restart. | InMemory, live PostgreSQL, controlled restart |

## Authority and evidence boundary

The scenarios use only `loom-api`/`loom-client` formal surfaces. World Time is
asserted using explicit `WorldInstant` values and TimelineVersion CAS; no wall
clock or elapsed-time measurement is authority. Logical Work status and
chronology budget are observed through `AdminService::timeline_logical_status`,
never through storage tables, leases, `available_at`, or SQL ordering.

The T13 race protocol is enabled as specified by the implementation standard:

- R-01: explicit-time Timeline CAS and due-work quiescence fence;
- R-02: EventSeq-ordered chronology reconstruction from committed history;
- R-03: reaction Work scheduling in the triggering logical commit.

Authority remains the Runtime-owned Timeline logical journal. The linearization
point remains the Timeline CAS logical commit; the only clock input is the
explicit request `WorldInstant`; rejection preserves authoritative state.

## Acceptance and progress

- [ ] CV-021..CV-024 implement the frozen matrix with no placeholder Pass.
- [ ] Logical time is never inferred from wall-clock time.
- [ ] Due Work cannot be bypassed by the Validator fixture.
- [ ] Chronology and reaction assertions use formal observable state.
- [ ] Dedicated InMemory and live PostgreSQL/restart tests pass.
- [ ] fmt/check/clippy and repository architecture/ledger checks pass.

### Progress Log

- 2026-08-27 — Recreated T13 from `origin/main` `6e4a991a0cf0ffe560dd58d0984a3529ba33fb8a` after the previous candidate became unavailable. Implemented four local descriptors/executors and public-surface observations in the allowed production module; added dedicated InMemory and PostgreSQL/restart tests in the allowed test module. The aggregate test creates a fresh server/client for each CV so CV-023's controlled restart cannot leave CV-024 with a stale client. Removed the PostgreSQL environment-variable enablement gate; the canonical harness default is now used when no override is present.
- 2026-08-27 — D-LEADER-01 correction: aligned the CV-022 ledger observation with the implementation and frozen evidence. Due Pending Work is produced by the public `neutral.counter.seed` + `neutral.counter.increment` semantic reaction path; `AdminService::advance_world_time` is then rejected, with `AdminService::timeline_logical_status` and `TimelineService::inspect_timeline` observing unchanged logical state. No scenario semantics or scope changed.
