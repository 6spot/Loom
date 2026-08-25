---
task: M9-T1
issue: 182
status: completed
depends_on: [181]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 237
merge_sha: 0a76a356612414a02fbd590695680f3aee84bdff
---
# M9-T1 — Complete Runtime Revision history

- Extend M4 revision records with immutable build/core/Capability implementation refs, compatibility metadata, non-secret policy IDs and change summary.
- Activation is explicit, append-auditable and concurrency-safe; historical rows are never overwritten.
- Server startup validates registered build vs known/active revision; no implicit activation.
- Invalid/incompatible activation changes neither active revision nor World data.
- Provide Runtime-owned active/list/get/activation-history ports.
- Running Sessions retain their pinned revision.

## Acceptance
- [x] R1/R2 history survives restart/concurrency.
- [x] Invalid activation is World-neutral.
- [x] Running R1/new R2 Session behavior is exact.
- [x] InMemory/PostgreSQL + standard gates pass.

Architecture: `evolution.md`; Platform History separation.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.