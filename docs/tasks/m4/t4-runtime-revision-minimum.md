---
task: M4-T4
issue: 149
status: in_progress
depends_on: [147]
created_at: 2026-08-22
started_at: 2026-08-22
completed_at:
completion_pr:
merge_sha:
---

# M4-T4 — Minimum Runtime Revision ledger

## Goal

Introduce the minimum durable Platform History needed to assemble executions correctly before the richer M9 provenance/Admin work.

## Implementation contract

- Runtime owns stable Runtime Revision descriptors and immutable publication records.
- Persist active revision selection in InMemory/PostgreSQL; activation is platform history, never a World Event.
- Revision identifies exact installed Capability implementation versions/compatibility available to an Execution Assembly.
- Server/composition explicitly registers/confirms revisions; process startup does not silently redefine semantics.
- Incompatible active software makes execution unavailable; it never mutates World Binding.

## Forbidden shortcuts

No mutable version string without history, World Event for activation, secrets in revision metadata, or mid-execution revision switching.

## Acceptance

- [ ] Immutable revision/active state survives restart.
- [ ] Selection is concurrency-safe and compatibility checks typed.
- [ ] Activation changes no World history/state/binding.
- [ ] Fresh PostgreSQL migration + standard gates pass.

Architecture basis: `evolution.md`, `world-runtime.md` Execution Session/Assembly.

## Verification evidence

- `python3 tools/check_architecture.py` → `Loom architecture dependency policy: OK`.
- `cargo fmt --all -- --check` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy -p loom-runtime -p loom-storage --all-targets -- -D warnings` → passed.
- `cargo test --workspace --all-features` → passed; PostgreSQL fixtures skip when `LOOM_TEST_POSTGRES_URL` is unset.
- `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps` → passed.
- Runtime revision compatibility fixture → exact Capability identity/version selection and typed missing/version mismatch behavior pass.
- InMemory revision fixture → immutable publication, explicit first activation, stale generation rejection, and unchanged Timeline snapshot pass.
- PostgreSQL revision fixture → fresh migration, restart persistence, active selection, and World/Event neutrality are covered; live execution awaits configured PostgreSQL.

## Progress Log

- 2026-08-22 — Planned.
- 2026-08-22 — Implementing the Runtime-owned immutable revision descriptor and explicit Platform History registration/activation seam; Session pinning remains the dependent M4-T5 boundary.
- 2026-08-22 — Local implementation gates pass; awaiting review/merge for completion metadata.
