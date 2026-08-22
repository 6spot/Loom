---
task: M7-T2
issue: 83
status: planned
depends_on: [82]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M7-T2 — Atomic Reaction Work Scheduling

## Goal
Expand validated matching Events into durable Immediate Work in the same commit that makes those Events true.

## Required implementation
- Inspect validated Event types against registered Reactions before commit.
- Runtime allocates WorkIds, validates handler/payload, causal EventRef/origin and fan-out budget.
- Include generated Work in the same validated/commit boundary and logical Work history on both adapters.
- Work-produced Events may schedule later Work but never recursively execute it in the same transaction.

## Forbidden shortcuts
No post-commit `schedule`, immediate handler call, hidden side table or unbounded fan-out.

## Acceptance checklist
- [ ] matching Event atomically persists generated Work;
- [ ] nonmatching Event produces none;
- [ ] persistence failure rolls Event and Work back together;
- [ ] handler/schema/budget failures reject before commit;
- [ ] Work-produced Event behavior and restart parity pass;
- [ ] architecture/fmt/check/clippy/tests/rustdoc/PostgreSQL pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after #82.
