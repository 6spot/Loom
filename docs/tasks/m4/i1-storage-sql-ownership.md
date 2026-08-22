# M4-I1 — Centralize PostgreSQL SQL ownership in `loom-storage`

Status: **in_progress**

Issue: #209

## Goal

Make `loom-storage` the only Loom crate that owns PostgreSQL/SQLx implementation details and centralize production SQL before M5 expands the persistence surface.

## Architecture rule

PostgreSQL is a `loom-storage` implementation detail. Other Loom crates and applications consume Runtime-owned persistence contracts only. They must not contain production SQL, depend on SQLx, receive `PgPool`/PostgreSQL transaction handles, or bypass the storage adapter.

## Required changes

- Keep schema evolution and DDL under `crates/loom-storage/migrations/`.
- Put runtime SQL under `crates/loom-storage/sql/<domain>/`.
- PostgreSQL Rust adapters own transaction orchestration, parameter binding and row decoding, but load statements from SQL files rather than embedding production SQL literals.
- Keep the SQL directory organized by persistence domain so M5–M10 additions have explicit ownership.
- Add architecture checks for SQLx/PostgreSQL leakage outside `loom-storage` and for new inline production SQL in storage Rust source.
- Keep tests from creating a second production persistence path.

## Target layout

```text
crates/loom-storage/
├── migrations/
├── sql/
│   ├── health/
│   ├── world/
│   ├── timeline/
│   ├── event/
│   ├── work/
│   ├── binding/
│   ├── runtime_revision/
│   ├── session/
│   ├── logical_journal/
│   ├── ancestry/
│   ├── ingress/
│   └── projection/
└── src/postgres/
```

## Acceptance checklist

- [ ] Production SQL exists only under `crates/loom-storage/migrations/` or `crates/loom-storage/sql/`.
- [x] No non-storage crate depends on `sqlx` or uses PostgreSQL implementation types; enforced by the architecture checker.
- [x] Existing PostgreSQL migrations and persistence behavior remain compatible for the extracted Work queries.
- [x] Architecture checker rejects SQL/SQLx/PostgreSQL ownership leakage outside `loom-storage` and rejects new inline-SQL storage modules.
- [ ] Existing inline production SQL is fully migrated to centralized SQL files. Remaining explicit debt: `src/postgres.rs`, `src/postgres/commit.rs`.
- [x] Baseline architecture/fmt/check/clippy/tests/rustdoc and PostgreSQL 18 integration gates pass on PR #211 head `b6db80ff925348429af72c1c88293d4837829928`.
- [ ] Completion PR, merge SHA and final verification evidence are recorded here before marking completed.

## Evidence

- Implementation PR: #211 (draft while legacy inline SQL remains)
- Verified head: `b6db80ff925348429af72c1c88293d4837829928`
- CI run: `32578643547`
- CI result: Rust Architecture/fmt/check/clippy/tests/rustdoc **green**; PostgreSQL 18 schema/migration, World lifecycle, Template birth, public Runtime/API parity, reads, commit/CAS, Durable Work, stale fence, restart/resume and Runtime Revision ledger **green**.
- Integration merge SHA: pending

## Remaining closure work

1. Extract all production statements from `crates/loom-storage/src/postgres.rs` into domain SQL files and remove that file from the inline-SQL debt allowlist.
2. Extract all production statements from `crates/loom-storage/src/postgres/commit.rs` and remove the final allowlist entry.
3. Run the full gates again on the no-exemption candidate.
4. Merge, record merge SHA/final CI evidence, then mark this task and #209 completed.
