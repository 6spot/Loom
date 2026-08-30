---
task: VALR-T23
issue: 328
status: completed
depends_on: [327]
created_at: 2026-08-29
started_at: 2026-08-30
completed_at: 2026-08-30
completion_pr: 394
merge_sha: b225d9c36662432bc4f377d8d4f29d0f1ed763fa
architecture_decision_blocker: false
---

# VALR-T23 — Current-main core integrated gate

## Certified core candidate

T23 is complete for production candidate `02c55a6b5c34f227abfcb732a21bf6c390e22578`, the PR #393 merge that includes Architecture Amendment 0004 and the formal derived-resource read boundary.

The earlier T23 PASS on the pre-T27 candidate is historical input only and is not used as current certification evidence.

## Current evidence

PR #394 was an evidence-only descendant of the production candidate and merged as `b225d9c36662432bc4f377d8d4f29d0f1ed763fa`. Exact-head CI run `33288294125` completed both required jobs successfully.

Rust checks passed:

- dependency/security policy
- architecture policy
- Validator READY and Stage-1 authority gates
- Compose validation
- fmt
- workspace check
- strict workspace Clippy
- full `tools/test.sh --workspace --all-features`
- rustdoc with warnings denied

PostgreSQL 18 persistence contract passed:

- schema/migration
- World lifecycle
- Template birth
- public Runtime/API vertical parity
- read/CAS/Durable Work/stale-fence contracts
- Runtime restart/resume and Revision contracts
- Validator lifecycle live path
- Validator replay/fork live path
- T20 PostgreSQL live matrix and artifact upload

The production candidate itself also has exact-tree implementation evidence from PR #393 run `33269628735`; PR #393 head and merge share Git tree `71bb8da37f55cc5b1bb4c8ed0f004f47a4ebf00e`.

## Acceptance

- [x] Production candidate is fixed to `02c55a6b5c34f227abfcb732a21bf6c390e22578`.
- [x] T22 represents exactly CV-001..CV-040 and records 40 ready / 0 gap.
- [x] CV-028/CV-029 rely on formal LoomClient observation and controlled setup only.
- [x] No old 38/2 result is promoted into current certification evidence.
- [x] Dependency/security, architecture, fmt, check, strict Clippy, full tests and rustdoc passed.
- [x] Complete PostgreSQL 18 persistence and live Validator gates passed.
- [x] PR #394 merged and durable completion evidence is recorded.
