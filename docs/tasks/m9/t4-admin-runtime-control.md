---
task: M9-T4
issue: 185
status: planned
depends_on: [155, 157, 182, 183, 184]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M9-T4 — Isolated Admin / Runtime Control API

- Separate Admin namespace/authorization from ordinary World API.
- Expose revision active/list/get/activate, Session/provenance, Event→Session, missing-implementation/chronology status.
- Expose authorized Work `Dead`/`Cancelled` and explicit World-Time control through exact M5 Runtime logical CAS/journal path.
- Admin reads/revision activation are World-neutral; logical controls change only their defined Timeline Logical State.
- Public DTOs expose no PgPool/SQL rows/ValidatedResolution/registry/secrets.
- Boundary/client use isolated admin routes and authorization hook.

## Acceptance
- [ ] Queries/control survive restart.
- [ ] Revision activation leaves World truth unchanged.
- [ ] Work/time controls obey CAS/quiescence/journal.
- [ ] Unauthorized/incompatible operations fail with no mutation.
- [ ] Architecture/integration + standard gates pass.

## Verification evidence
Pending.