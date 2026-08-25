---
task: M8-T1
issue: 174
status: completed
depends_on: [173]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at: 2026-08-23
completion_pr: 230
merge_sha: d36167c3ad20fbf76181c5c51e6d1c7074d336a9
---
# M8-T1 — Ingress and Subscription API contracts

- Transport-neutral Ingress envelope: stable ID/idempotency, source/provenance, target, opaque auth policy context, source/platform metadata, ActionInvocation.
- Distinguish accepted/deduped, completed semantic result, semantic rejection and technical failure/retry.
- Change Feed cursor is committed Timeline history identity, not process notification identity.
- Define reconnect/resume/end/backpressure values without transport types.
- Keep Admin/Runtime Control separate from ordinary World API.

## Forbidden
No HTTP types in `loom-api`, direct Ingress Event/Effect/commit endpoint, accepted-as-World-truth, or subscriber authority.

## Acceptance
- [x] Contracts serialize/document cleanly.
- [x] Result/lifecycle states are unambiguous.
- [x] Idempotency conflict + feed cursor/resume are explicit/bounded.
- [x] API dependency DAG + standard gates pass.

Architecture: Amendment 0001 §6.2.

## Verification evidence
- `crates/loom-api/src/lib.rs` defines transport-neutral Ingress envelope,
  idempotency acceptance/conflict, platform status, completed commit/no-change/
  semantic-rejection results and technical retry/failure states.
- The same public crate defines Timeline/EventSeq Change Feed cursors, bounded
  page requests, resume/reconnect/end/backpressure values and a focused
  `SubscriptionService`; no callback, process notification ID or transport
  type is exposed.
- `cargo fmt --all -- --check` passed.
- `cargo check --workspace` passed.
- `cargo clippy --workspace --all-targets -- -D warnings` passed.
- `cargo test --workspace` passed.
- `cargo doc --workspace --no-deps` passed.
