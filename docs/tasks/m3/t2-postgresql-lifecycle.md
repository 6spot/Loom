---
task: M3-T2
issue: 49
status: in_progress
depends_on: [48]
created_at: 2026-08-21
started_at: 2026-08-21
completed_at:
completion_pr:
merge_sha:
---

# M3-T2 — PostgreSQL Lifecycle Persistence

## Goal

Harden and prove the Runtime-owned World lifecycle persistence port on PostgreSQL 18 with atomic World + initial Timeline creation and isolated integration coverage.

## Acceptance checklist

- [ ] `PgStorage` implements the lifecycle port without leaking SQLx into Runtime/API;
- [ ] World and initial Timeline are inserted in one transaction;
- [ ] initial version/time values exactly match the Runtime request;
- [ ] duplicate/conflicting identity creation rolls back completely;
- [ ] existing `WorldStore::snapshot` and public Timeline inspection see the new Timeline after commit;
- [ ] isolated PostgreSQL integration tests cover success and rollback semantics;
- [ ] CI explicitly executes the lifecycle suite alongside existing PostgreSQL contracts.

## Completion evidence

- PR:
- merge SHA:
- CI runs:
- notes:

## Progress log

- 2026-08-21 — Task record created; waits on M3-T1 #48.
- 2026-08-21 — Started from T1 completion/audit main `02527ee48a7a08cc4c508c19512fa38155746ea5`. T1 already introduced the minimal `PgStorage` lifecycle implementation; T2 audits transaction/error classification and adds dedicated PostgreSQL 18 lifecycle success/conflict/rollback/readability evidence plus an explicit CI gate.
