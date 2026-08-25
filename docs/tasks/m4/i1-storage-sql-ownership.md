---
task: M4-I1
issue: 209
status: completed
depends_on: [152]
created_at: 2026-08-22
started_at: 2026-08-22
completed_at: 2026-08-22
completion_pr: 211
merge_sha: d2b84d0740ade1c361037c270b11cfb6d960e66e
---
# M4-I1 — Centralize PostgreSQL SQL ownership in `loom-storage`

Status: **completed**

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

- [x] Production SQL exists only under `crates/loom-storage/migrations/` or `crates/loom-storage/sql/`.
- [x] No non-storage crate depends on `sqlx` or uses PostgreSQL implementation types; enforced by the architecture checker.
- [x] Existing PostgreSQL migrations and persistence behavior remain compatible for the extracted Work queries.
- [x] Architecture checker rejects SQL/SQLx/PostgreSQL ownership leakage outside `loom-storage` and rejects new inline-SQL storage modules.
- [x] Existing inline production SQL is fully migrated to centralized SQL files; PR #211 removed the final inline-SQL exemptions.
- [x] Baseline architecture/fmt/check/clippy/tests/rustdoc and PostgreSQL 18 integration gates pass on PR #211 head `b6db80ff925348429af72c1c88293d4837829928`.
- [x] Completion PR, merge SHA and final verification evidence are recorded here before marking completed.

## Evidence

- Implementation PR: #211
- Verified head: `b6db80ff925348429af72c1c88293d4837829928`
- CI run: `32578643547`
- CI result: Rust Architecture/fmt/check/clippy/tests/rustdoc **green**; PostgreSQL 18 schema/migration, World lifecycle, Template birth, public Runtime/API parity, reads, commit/CAS, Durable Work, stale fence, restart/resume and Runtime Revision ledger **green**.
- Integration merge SHA: `d2b84d0740ade1c361037c270b11cfb6d960e66e`

## Completion audit

PR #211 merged as `d2b84d0740ade1c361037c270b11cfb6d960e66e`; its zero-exemption
storage SQL ownership implementation and CI run `32578643547` satisfy the
remaining closure work recorded above. The final M13-T1 candidate re-ran the
architecture and PostgreSQL contract gates on the integrated baseline.
