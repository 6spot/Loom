---
task: M4-T4
issue: 149
status: completed
depends_on: [147]
created_at: 2026-08-22
started_at: 2026-08-22
completed_at: 2026-08-22
completion_pr: 207
merge_sha: 14d2b7cc3f0a5f3c80e9fa9dfc299eb688c37350
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

- [x] Immutable revision/active state survives restart.
- [x] Selection is concurrency-safe and compatibility checks typed.
- [x] Activation changes no World history/state/binding.
- [x] Fresh PostgreSQL migration + standard gates pass.

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
- PostgreSQL revision fixture → fresh migration, restart persistence, active selection, and World/Event neutrality pass against PostgreSQL 18.
- PR #207 merged as `14d2b7cc3f0a5f3c80e9fa9dfc299eb688c37350`; post-merge CI run `32574908686` passed the Rust and PostgreSQL 18 jobs.

## Progress Log

- 2026-08-22 — Planned.
- 2026-08-22 — Implementing the Runtime-owned immutable revision descriptor and explicit Platform History registration/activation seam; Session pinning remains the dependent M4-T5 boundary.
- 2026-08-22 — Local implementation gates pass; awaiting review/merge for completion metadata.
- 2026-08-22 — Accepted and merged as PR #207; post-merge CI run `32574908686` passed.
