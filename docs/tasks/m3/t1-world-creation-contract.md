---
task: M3-T1
issue: 48
status: in_progress
depends_on: []
created_at: 2026-08-21
started_at: 2026-08-21
completed_at:
completion_pr:
merge_sha:
---

# M3-T1 — Public World Creation Contract + Runtime Lifecycle/Identity Ports + InMemory Parity

## Goal

Define the unified public and Runtime-owned boundaries for creating one empty World plus its initial Timeline, then prove the in-memory adapter obeys the same atomic lifecycle contract used by later PostgreSQL work.

## Acceptance checklist

- [ ] `loom-api` exposes a focused `WorldService` and the unified `LoomApi` includes it;
- [ ] public create request/result contain only Loom semantic values and read models;
- [ ] Runtime owns an injectable identity allocator boundary;
- [ ] default Runtime identity allocation uses UUIDv7 without leaking UUID implementation into `loom-api`;
- [ ] Runtime owns a lifecycle persistence port for atomic World + initial Timeline bootstrap;
- [ ] initial Timeline version is zero and requested World semantic time is preserved;
- [ ] duplicate/conflicting identities fail without partial state and map to public conflict semantics;
- [ ] `InMemoryStore` implements lifecycle creation atomically while existing fixture helpers remain available;
- [ ] a publicly created Timeline can immediately execute a normal semantic Action through Runtime validation/commit authority;
- [ ] all new public Core/API/Runtime abstractions have semantic Rust documentation;
- [ ] architecture policy stays green and no Storage/SQL/UUID implementation leaks into `loom-api`.

## Verification

- [ ] `python3 tools/check_architecture.py`;
- [ ] `cargo fmt --all -- --check`;
- [ ] `cargo check --workspace --all-targets --all-features`;
- [ ] `cargo clippy --workspace --all-targets --all-features -- -D warnings`;
- [ ] `cargo test --workspace --all-features`;
- [ ] `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps`;
- [ ] focused creation/allocation/conflict/InMemory composition tests.

## Completion evidence

- PR:
- merge SHA:
- CI runs:
- notes:

## Progress log

- 2026-08-21 — Task started from Milestone 2 closure baseline `e9fde033fe375f9e03f20ef82d37f466e4ff1db2`. Scope intentionally stops at unified API + Runtime lifecycle/identity boundaries and InMemory parity; PostgreSQL implementation is #49.
