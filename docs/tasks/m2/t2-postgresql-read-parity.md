---
task: M2-T2
issue: 27
status: completed
depends_on: [26]
created_at: 2026-08-21
started_at: 2026-08-21
completed_at: 2026-08-21
completion_pr: 36
merge_sha:
---

# M2-T2 — PostgreSQL WorldStore and Snapshot/Read Parity

## Goal

Implement PostgreSQL-backed Runtime read ports so pinned Timeline snapshots expose the same authoritative World/current-state/history semantics as the Milestone 1 in-memory adapter.

## Scope

- Implement PostgreSQL `WorldStore`/snapshot reads through Runtime-owned contracts.
- Reconstruct TimelineVersion and World Time exactly.
- Load current Entity/Relationship structure and entity/relationship Facets.
- Load committed Event history/order and structural/causal references required by Runtime/API inspection.
- Keep SQLx/PgPool inside `loom-storage`.
- Never infer authoritative Event order from UUID or database timestamps.

## Acceptance checklist

- [x] empty Timeline snapshot parity;
- [x] Entity/Relationship/Facet snapshot parity;
- [x] Event history and EventSeq ordering parity;
- [x] World Time and TimelineVersion parity;
- [x] ended Relationship/current-state semantics match Milestone 1;
- [x] missing Timeline maps to the expected typed Runtime-facing error;
- [x] architecture, fmt, check, clippy, tests and rustdoc pass.

## Completion evidence

- PR: #36
- merge SHA: pending post-merge audit update
- CI / verification: GitHub Actions run `32452222573` — PostgreSQL 18 persistence contract success; Rust Ubuntu success; Rust macOS success; Architecture, Format, Check, Clippy, Test and Rustdoc all green on both Rust runners.
- notes: PostgreSQL snapshot reads use a `REPEATABLE READ READ ONLY` transaction; Event history is ordered by authoritative `EventSeq`, with a fixture whose UUID order intentionally differs; empty Timeline parity is covered by `crates/loom-storage/tests/postgres_read.rs`. Public/Runtime persistence I/O is executor-neutral Future-returning while Capability semantic resolution remains synchronous over pinned in-memory views. The narrow PostgreSQL module lint expectation documents a temporary source-layout hotspot and is to be removed as T3/T4 split the adapter by Runtime persistence port.

## Progress log

- 2026-08-21 — Task record created from issue #27; status `planned`.
- 2026-08-21 — Implementation started on `feat/m2-t2-postgresql-read-parity`; status `in_progress`.
- 2026-08-21 — PostgreSQL implementation evidence exposed a contract mismatch: SQLx persistence is asynchronous while Milestone 1 Runtime persistence ports/public I/O services were synchronous. T2 migrated only persistence I/O boundaries to object-safe, executor-neutral Future-returning contracts. Capability Resolver/Invariant/ResolutionContext remain synchronous over the already-pinned in-memory World view, so no database I/O or async executor leaks into semantic extension code.
- 2026-08-21 — Strict clippy review identified PostgreSQL source-layout hotspots. Temporary branch helper workflows were removed before completion; a narrow module expectation records the hotspot until T3/T4 split the concrete adapter by Runtime persistence port.
- 2026-08-21 — Added explicit empty Timeline PostgreSQL snapshot parity coverage and completed all T2 gates in CI run `32452222573`.
