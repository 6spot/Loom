---
task: M4-T5
issue: 150
status: completed
depends_on: [147, 149]
created_at: 2026-08-22
started_at: 2026-08-22
completed_at: 2026-08-22
completion_pr: 212
merge_sha: dc3543f22454c133da7ce9958031c7a6fd2df1db
---

# M4-T5 — Root Execution Session and exact Execution Assembly

## Goal

Pin every root world-affecting execution to one immutable World/Timeline/version/Binding/Runtime Revision/exact implementation assembly.

## Implementation contract

- Runtime owns Session ID/origin/context and `ExecutionAssembly`.
- Session start pins World/Timeline, TimelineVersion, Binding, active Runtime Revision, exact compatible Capability implementations and execution policy/environment.
- Action, Work, Ingress and Template bootstrap roots use exactly one Session; subresolution remains in the same assembly.
- Persist minimum Session lifecycle/origin/revision/implementation evidence now; M9 enriches evidence later.
- Running Session never switches revision/implementation if active revision changes concurrently.
- Missing compatible software before semantic execution starts consumes no technical Work attempt.

## Forbidden shortcuts

No process-global mutable current Session, mid-subresolution registry rebinding, Session World Events, or mutation of Binding to pin implementations.

## Acceptance

- [x] Direct Action/subresolution stays in one assembly.
- [x] Concurrent activation cannot change running Session.
- [x] Work/Ingress/bootstrap roots use same Session contract.
- [x] Missing software starts no execution/attempt.
- [x] Minimum Session records survive restart and standard gates pass.

Architecture basis: `world-runtime.md` Execution Session; Amendment 0002 §5; Amendment 0003 §3.

## Verification evidence

- `python3 tools/check_architecture.py` → `Loom architecture dependency policy: OK`.
- `cargo fmt --all -- --check` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed.
- `cargo test --workspace --all-targets --all-features` → passed; PostgreSQL integration fixtures return early when `LOOM_TEST_POSTGRES_URL` is unset.
- `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --all-features --no-deps` → passed.
- InMemory Session/Assembly fixtures → direct Action/subresolution keeps one Application Session, active-revision switching keeps the original revision/implementation, Template bootstrap records Runtime origin, and missing Work software leaves attempt count/lease/session unchanged.
- PostgreSQL Session/restart fixture → passes live against PostgreSQL 18 and asserts Template/Action/Work lifecycle records survive adapter restart.
- PR #212 merged as `dc3543f22454c133da7ce9958031c7a6fd2df1db`; post-merge CI run `32579121710` passed the Rust and PostgreSQL 18 jobs.

## Progress Log

- 2026-08-22 — Planned.
- 2026-08-22 — Started Runtime-owned Session/Assembly implementation after M4-T4 revision ledger became available; Ingress remains the later M8 public boundary.
- 2026-08-22 — Added Runtime-owned immutable Session/Assembly lifecycle, InMemory/PostgreSQL persistence, root wiring, active-revision and missing-Work fixtures; local gates pass and the task is awaiting acceptance.
- 2026-08-22 — Accepted and merged as PR #212; post-merge CI run `32579121710` passed.
