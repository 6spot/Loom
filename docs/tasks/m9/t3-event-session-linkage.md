---
task: M9-T3
issue: 184
status: completed
depends_on: [183]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 239
merge_sha: 6dc7327cf1bdf950f77c371f3a43e3983153dd11
---
# M9-T3 — Atomic Event ↔ Session linkage

- World Event commit and Session→EventRef provenance linkage share required transaction/linearization guarantee.
- Link only fixed Event IDs produced/validated by current Session.
- Apply uniformly to Action/Work/Reaction/Ingress/bootstrap/later Agency.
- Logical-only/no-change/rejected/failed Sessions finalize with zero fake Event refs.
- Crash recovery cannot leave a permanently committed Event orphaned from required Session evidence.
- Query EventRef→Session and Session→ordered EventRefs.

## Forbidden
No best-effort async link, Session ID in payload, causal-link reuse, or Storage-generated Session.

## Acceptance
- [x] Exactly one producing Session per committed Event.
- [x] Forced rollback/crash cannot orphan links.
- [x] Restart parity + standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.