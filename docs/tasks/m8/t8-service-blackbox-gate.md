---
task: M8-T8
issue: 181
status: completed
depends_on: [174, 175, 176, 177, 178, 179, 180]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 236
merge_sha: db0049822e361afb438c5d4562520cca1cc6a127
---
# M8-T8 — Service black-box gate

From clean PostgreSQL18+pgvector/blob: start server, discover Template/catalog, create World, invoke Action, query State/History, subscribe SSE, submit duplicate Ingress, create due/Reaction Work, kill before execution/finalization, restart, observe Scheduler/Ingress recovery, resume SSE and repeat through formal client.

## Assertions
- [x] World birth preserves Binding/Session semantics.
- [x] HTTP/Ingress cannot bypass Action authority.
- [x] Duplicate Ingress causes at most one World mutation.
- [x] Scheduler resumes logical head/fence safely.
- [x] SSE derives from committed history with no gap.
- [x] Disabled semantics remain unavailable.
- [x] Restart changes no Binding/World-Time/logical-order/revision history.
- [x] Black-box + architecture/fmt/check/clippy/tests/rustdoc/PostgreSQL gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.