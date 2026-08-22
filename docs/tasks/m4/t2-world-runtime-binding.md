---
task: M4-T2
issue: 147
status: completed
depends_on: [146]
created_at: 2026-08-22
started_at: 2026-08-22
completed_at: 2026-08-22
completion_pr: 206
merge_sha: a716f636677d4b1b915024bcb2fe1a0dc5656baa
---

# M4-T2 — Immutable World Runtime Binding

## Goal

Persist World Runtime Binding as World-level Runtime Metadata and eliminate implicit `installed registry == enabled for this World` behavior.

## Implementation contract

- Runtime owns the binding descriptor/ports; Storage implements persistence.
- Binding stores semantic Capability IDs, compatibility requirements and immutable World config — never resolver objects or permanently pinned exact binaries.
- Binding is shared by all Timelines of one World and immutable in v0.
- Direct Action routing must enforce it immediately; later Work/Reaction/retrieval tasks reuse the same lookup boundary.
- Add additive InMemory/PostgreSQL persistence.
- Migrate M3-era Worlds by an explicit one-time compatibility binding; no live fallback to all currently installed software.

## Forbidden shortcuts

No per-Timeline binding, Template live subscription, exact Session implementation stored as binding, or registry-presence fallback after migration.

## Acceptance

- [x] Different Worlds can have different bindings under one installed registry.
- [x] Disabled installed Action is unavailable.
- [x] Binding survives restart and cannot mutate in v0.
- [x] Legacy data receives deterministic persisted binding.
- [x] InMemory/PostgreSQL + standard gates pass.

Architecture basis: `world-runtime.md` Binding; `implementation.md` Binding/Execution Assembly distinction.

## Verification evidence

- `python3 tools/check_architecture.py` → `Loom architecture dependency policy: OK`.
- `cargo fmt --all -- --check` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed.
- `cargo test --workspace --all-features` → passed; PostgreSQL integration fixtures return early when `LOOM_TEST_POSTGRES_URL` is unset.
- `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps` → passed.
- InMemory binding tests → World-keyed sharing, one-time legacy materialization, and overwrite rejection pass.
- PostgreSQL lifecycle binding test → passed live against PostgreSQL 18, including restart survival and mutation rejection.
- PR #206 merged as `a716f636677d4b1b915024bcb2fe1a0dc5656baa`; post-merge CI run `32571901477` passed the Rust and PostgreSQL 18 jobs.

## Progress Log

- 2026-08-22 — Planned.
- 2026-08-22 — Implemented the Runtime-owned immutable World binding descriptor/port, additive InMemory/PostgreSQL persistence, explicit M3 compatibility materialization, and direct Action enablement enforcement; awaiting acceptance and live PostgreSQL evidence.
- 2026-08-22 — Accepted and merged as PR #206; post-merge CI run `32571901477` passed, and the PostgreSQL binding/lifecycle suite was revalidated locally.
