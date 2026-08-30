---
task: SCHD-T10
issue: 412
status: completed
depends_on: [411]
created_at: 2026-08-30
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 445
merge_sha: ac851f6dfaa6643f997aef4cabaadc7bc46701e9
---

# SCHD-T10 — Implement one bounded Scheduler discovery/drive cycle

## Goal

Implement one bounded Supervisor cycle that discovers through Runtime and
drives each discovered target once through `Runtime::drive_timeline`.

## Scope and acceptance

- [x] Use `WorkerConfig::scheduler_poll_limit()` as both the existing bounded
      discovery/drive limit and no new discovery configuration.
- [x] Sample platform timing as required and call `drive_timeline` once per
      discovered target.
- [x] Treat normal Executed/Blocked/Advanced/Idle/budget outcomes as per-target
      results and do not reinterpret them as another target's chronology.
- [x] Empty, bounded-N, exact-target and normal Blocked/Idle tests pass.
- [x] No long-running loop, cursor fairness beyond the page, parallel spawn,
      direct claim or server composition change is included.

## Progress Log

- 2026-08-30 — Implemented `SchedulerSupervisor::run_cycle` using the Runtime
  discovery façade, the existing scheduler poll limit and sequential
  `Runtime::drive_timeline` calls. Added an application-owned cycle report and
  coverage for empty, bounded, exact-target, Blocked and stale-discovery Idle
  outcomes.
- 2026-08-30 — Addressed the Supervisor Clippy findings by using the discovery
  target method item and borrowing discovery errors for API mapping. Reclaimed
  disposable host cache space and completed the focused and standard Rust
  checks.
- 2026-08-30 — Upstream canonical Scheduler ledger drift was reconciled on
  `main` through SCHD-T09 by PR #446. This evidence-only update intentionally
  retriggered PR #445 against the corrected prerequisite chain; no T10
  implementation semantics changed.
- 2026-08-30 — Delivery PR #445 merged as
  `ac851f6dfaa6643f997aef4cabaadc7bc46701e9`; canonical completion metadata is
  reconciled here before SCHD-T11 proceeds.

## Verification Evidence

- `cargo fmt --all -- --check` — passed.
- `git diff --check` — passed.
- `CARGO_PROFILE_DEV_DEBUG=0 CARGO_INCREMENTAL=0 cargo test -p loom-server
  --lib -j1` — passed (14 tests).
- `CARGO_PROFILE_DEV_DEBUG=0 CARGO_INCREMENTAL=0 cargo check --workspace
  --exclude loom-validator --all-targets --all-features` — passed.
- `CARGO_PROFILE_DEV_DEBUG=0 CARGO_INCREMENTAL=0 cargo clippy --workspace
  --exclude loom-validator --all-targets --all-features -- -D warnings` —
  passed.
- `CARGO_PROFILE_DEV_DEBUG=0 CARGO_INCREMENTAL=0 cargo test --workspace
  --all-features --exclude loom-storage --exclude loom-validator` — passed.
- `CARGO_PROFILE_DEV_DEBUG=0 CARGO_INCREMENTAL=0 cargo test -p loom-storage
  --all-features --lib` — passed (65 tests, including PostgreSQL coverage).
- PR #445 CI run `33320623354` — passed: Task Ledger governance and Rust checks
  succeeded; PostgreSQL/dependency/deployment lanes were correctly skipped.
