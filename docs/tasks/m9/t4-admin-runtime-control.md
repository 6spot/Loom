---
task: M9-T4
issue: 185
status: completed
depends_on: [155, 157, 182, 183, 184]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 240
merge_sha: 0c80441c2136256fbd7ab0925658411aee70e934
---
# M9-T4 — Isolated Admin / Runtime Control API

- Separate Admin namespace/authorization from ordinary World API.
- Expose revision active/list/get/activate, Session/provenance, Event→Session, missing-implementation/chronology status.
- Expose authorized Work `Dead`/`Cancelled` and explicit World-Time control through exact M5 Runtime logical CAS/journal path.
- Admin reads/revision activation are World-neutral; logical controls change only their defined Timeline Logical State.
- Public DTOs expose no PgPool/SQL rows/ValidatedResolution/registry/secrets.
- Boundary/client use isolated admin routes and authorization hook.

## Acceptance
- [x] Queries/control survive restart.
- [x] Revision activation leaves World truth unchanged.
- [x] Work/time controls obey CAS/quiescence/journal.
- [x] Unauthorized/incompatible operations fail with no mutation.
- [x] Architecture/integration + standard gates pass.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.