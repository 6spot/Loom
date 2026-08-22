---
task: M4-T7
issue: 152
status: in_review
depends_on: [146, 147, 148, 149, 150, 151]
created_at: 2026-08-22
started_at: 2026-08-22
completed_at:
completion_pr: 215
merge_sha:
---

# M4-T7 — Reconciliation final gate

## Goal

Revalidate the real M1–M3 assets under the current architecture and establish the only supported baseline for M5+.

## Revalidation checklist

- [x] Fresh PostgreSQL 18 migration includes the legacy-binding, Runtime Revision and Execution Session authority tables; `postgres_schema` asserts all four table names.
- [x] The neutral composition fixture registers counter and observer Capabilities, activates R1, creates two Template-backed Worlds through `loom-api`, and inspects exact Binding plus Runtime bootstrap Sessions.
- [x] Successful, rejected, zero-effect/NoChange and cross-Capability subresolution paths remain covered by `neutral_templates`, `vertical_slice`, `postgres_vertical` and `subresolution`; cross-Capability resolution records one pinned Application Session and one flattened commit.
- [x] Runtime-stamped Event occurrence equals pinned World Time and ordinary commits leave World Time unchanged in the neutral and PostgreSQL vertical assertions.
- [x] PostgreSQL `postgres_restart_resume` reconstructs Runtime/storage and continues the same World with durable Event/State/Work/Session history.
- [x] Neutral composition executes one Action under R1, switches to compatible R2, and proves the earlier Session remains R1 while the next Session is R2.
- [x] Neutral composition activates an incompatible revision and proves Action admission is unavailable with unchanged World Binding, Event history and Session count.

## Required scenario

- Fresh PostgreSQL 18 migration including Binding/Revision/Session additions.
- Register neutral Capabilities + Runtime Revision R1 and create a Template-backed World.
- Exercise success/rejection/no-change and cross-Capability subresolution through pinned Session/Assembly.
- Verify Runtime-stamped Event time and no implicit World-Time advancement.
- Restart and continue the World.
- Activate compatible R2 and prove old Session remains R1, next Session uses R2.
- Try incompatible assembly and prove execution unavailable while World/Binding/history remain unchanged.

## Final gates

- [x] Architecture checker.
- [x] fmt/check/clippy `-D warnings`/workspace tests/rustdoc `-D warnings`.
- [x] PostgreSQL schema/read/commit/CAS/Work/restart/revision suites.
- [x] M4-T1 through M4-T6 task records are aligned with their `done` Issues and carry merged PR/SHA/CI evidence.

## Verification evidence

### AC-to-evidence mapping

- `AC-1` migration and authority additions → `crates/loom-storage/tests/postgres_schema.rs` → PostgreSQL 18 `postgres_schema` passed.
- `AC-2` neutral Capabilities, R1, Template birth, Binding and bootstrap Session → `tests/loom-composition/neutral_templates.rs` → 2 tests passed.
- `AC-3` Action success/rejection/NoChange and cross-Capability flattening → `crates/loom-storage/tests/postgres_vertical.rs`, `crates/loom-storage/tests/postgres_commit.rs`, `tests/loom-composition/subresolution.rs` → 1 + 8 + 11 tests passed.
- `AC-4` Event/World-Time authority → `tests/loom-composition/neutral_templates.rs`, `crates/loom-storage/tests/postgres_vertical.rs`, `crates/loom-storage/tests/postgres_commit.rs` → occurrence-time and no-advance assertions passed.
- `AC-5` restart/resume → `crates/loom-storage/tests/postgres_restart_resume.rs` → 1 PostgreSQL 18 test passed.
- `AC-6` compatible revision switch and Session pinning → `tests/loom-composition/neutral_templates.rs`, `tests/loom-composition/subresolution.rs`, `crates/loom-storage/tests/postgres_revision.rs` → all passed.
- `AC-7` incompatible active assembly is unavailable without rebinding or history mutation → `tests/loom-composition/neutral_templates.rs` → assertion passed.

### PostgreSQL evidence

- Local disposable `postgres:18`: `LOOM_TEST_POSTGRES_URL=postgresql://loom:loom@localhost:5432/loom_control LOOM_REQUIRE_POSTGRES_TESTS=1 cargo test -p loom-storage --tests --all-features -- --nocapture` → all integration suites passed: schema, commit/CAS, lifecycle/template birth, read, restart/resume, revision, vertical, Work and stale-fence.
- Baseline CI run `32580431020` for merged M4-T6 `b876e8e` passed both Rust checks and the PostgreSQL 18 persistence contract, including schema/lifecycle/template/vertical/read/commit/Work/stale-fence/restart/revision steps.

### Completion evidence

- Code candidate SHA: `7daf76a` (`ME-191: strengthen M4 reconciliation evidence`).
- PR #215 is open for acceptance/merge.
- The M4-T1–T6 records now carry their merged PR/SHA/CI evidence; no production/runtime architecture semantics were added by this gate.

## Progress Log

- 2026-08-22 — Added direct neutral R1/R2/incompatible revision admission assertions, explicit PostgreSQL authority-table and occurrence-time checks, and ran the full local standard/PostgreSQL gate. PR #215 is open for acceptance.
