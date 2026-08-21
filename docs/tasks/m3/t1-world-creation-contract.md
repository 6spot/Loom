---
task: M3-T1
issue: 48
status: in_progress
depends_on: []
created_at: 2026-08-21
started_at: 2026-08-21
completed_at:
completion_pr: 52
merge_sha:
---

# M3-T1 — Public World Creation Contract + Runtime Lifecycle/Identity Ports + InMemory Parity

## Goal

Define the unified public and Runtime-owned boundaries for creating one empty World plus its initial Timeline, then prove the in-memory adapter obeys the same atomic lifecycle contract used by later PostgreSQL work.

## Acceptance checklist

- [x] `loom-api` exposes a focused `WorldService` and the unified `LoomApi` includes it;
- [x] public create request/result contain only Loom semantic values and read models;
- [x] Runtime owns an injectable identity allocator boundary;
- [x] default Runtime identity allocation uses UUIDv7 without leaking UUID implementation into `loom-api`;
- [x] Runtime owns a lifecycle persistence port for atomic World + initial Timeline bootstrap;
- [x] initial Timeline version is zero and requested World semantic time is preserved;
- [x] duplicate/conflicting identities fail without partial state and map to public conflict semantics;
- [x] `InMemoryStore` implements lifecycle creation atomically while existing fixture helpers remain available;
- [x] a publicly created Timeline can immediately execute a normal semantic Action through Runtime validation/commit authority;
- [x] all new public Core/API/Runtime abstractions have semantic Rust documentation;
- [x] architecture policy stays green and no Storage/SQL/UUID implementation leaks into `loom-api`.

## Verification

- [x] `python3 tools/check_architecture.py`;
- [x] `cargo fmt --all -- --check`;
- [x] `cargo check --workspace --all-targets --all-features`;
- [x] `cargo clippy --workspace --all-targets --all-features -- -D warnings`;
- [x] `cargo test --workspace --all-features`;
- [x] `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps`;
- [x] focused creation/allocation/conflict/InMemory composition coverage via `world_creation::public_world_creation_is_atomic_and_immediately_usable`, including duplicate World ID, Timeline-ID conflict rollback, exact initial version/time, and immediate semantic Action execution.

## Completion evidence

- PR: #52
- merge SHA: pending implementation merge
- clean candidate SHA: `76002e1170b68cf122ff8c9bec409b7ece3bbe85`
- CI runs: `32469168089` (write-enabled implementation verifier, green before temporary verifier removal); `32488685071` (clean standard CI, Ubuntu/macOS/PostgreSQL 18 all green)
- notes: T1 includes the minimal `PgStorage` lifecycle-port implementation needed to keep `Runtime<PgStorage>` a complete unified `LoomApi`; dedicated PostgreSQL lifecycle transaction/conflict integration hardening remains serial T2 #49. Task remains `in_progress` until #52 merges and a post-merge audit records the real merge SHA.

## Progress log

- 2026-08-21 — Task started from Milestone 2 closure baseline `e9fde033fe375f9e03f20ef82d37f466e4ff1db2`.
- 2026-08-21 — Implemented public World creation, Runtime-owned identity/lifecycle boundaries, atomic InMemory bootstrap, minimal Pg lifecycle adapter, and composition coverage. Temporary write-enabled verifier `32469168089` passed architecture/check/clippy/tests/rustdoc and committed the verified source changes; temporary workflow/scripts were then removed from the PR.
- 2026-08-21 — Added independent Timeline-ID conflict rollback coverage so a fresh World ID paired with an existing Timeline ID fails atomically; a subsequent retry with that same World ID and a fresh Timeline succeeds, proving no partial World remained.
- 2026-08-21 — Clean candidate `76002e1170b68cf122ff8c9bec409b7ece3bbe85` passed standard CI `32488685071`: Ubuntu and macOS architecture/fmt/check/clippy/workspace tests/rustdoc green; PostgreSQL 18 schema, public Runtime/API vertical, read, commit/CAS, Durable Work, and stale-fence suites green. Awaiting merge + post-merge audit for completion metadata.
