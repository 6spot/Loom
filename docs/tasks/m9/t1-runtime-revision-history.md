---
task: M9-T1
issue: 182
status: planned
depends_on: [181]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M9-T1 — Complete Runtime Revision history

- Extend M4 revision records with immutable build/core/Capability implementation refs, compatibility metadata, non-secret policy IDs and change summary.
- Activation is explicit, append-auditable and concurrency-safe; historical rows are never overwritten.
- Server startup validates registered build vs known/active revision; no implicit activation.
- Invalid/incompatible activation changes neither active revision nor World data.
- Provide Runtime-owned active/list/get/activation-history ports.
- Running Sessions retain their pinned revision.

## Acceptance
- [ ] R1/R2 history survives restart/concurrency.
- [ ] Invalid activation is World-neutral.
- [ ] Running R1/new R2 Session behavior is exact.
- [ ] InMemory/PostgreSQL + standard gates pass.

Architecture: `evolution.md`; Platform History separation.

## Verification evidence
Pending.