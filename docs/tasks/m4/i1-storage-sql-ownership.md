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
- [ ] No non-storage crate depends on `sqlx` or uses PostgreSQL implementation types.
- [ ] Existing PostgreSQL migrations and persistence behavior remain compatible.
- [ ] Architecture checker rejects representative SQL/SQLx leakage outside `loom-storage`.
- [ ] Existing inline production SQL is migrated to centralized SQL files.
- [ ] Architecture/fmt/check/clippy/tests/rustdoc and PostgreSQL integration gates pass.
- [ ] Completion PR, merge SHA and verification evidence are recorded here before marking completed.

## Evidence

- Completion PR: pending
- Integration merge SHA: pending
- CI / verification: pending
