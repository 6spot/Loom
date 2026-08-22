---
task: M8-T8
issue: 181
status: planned
depends_on: [174, 175, 176, 177, 178, 179, 180]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M8-T8 — Service black-box gate

From clean PostgreSQL18+pgvector/blob: start server, discover Template/catalog, create World, invoke Action, query State/History, subscribe SSE, submit duplicate Ingress, create due/Reaction Work, kill before execution/finalization, restart, observe Scheduler/Ingress recovery, resume SSE and repeat through formal client.

## Assertions
- [ ] World birth preserves Binding/Session semantics.
- [ ] HTTP/Ingress cannot bypass Action authority.
- [ ] Duplicate Ingress causes at most one World mutation.
- [ ] Scheduler resumes logical head/fence safely.
- [ ] SSE derives from committed history with no gap.
- [ ] Disabled semantics remain unavailable.
- [ ] Restart changes no Binding/World-Time/logical-order/revision history.
- [ ] Black-box + architecture/fmt/check/clippy/tests/rustdoc/PostgreSQL gates pass.

## Verification evidence
Pending.