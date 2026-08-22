---
task: M4-T6
issue: 66
status: planned
depends_on: [61, 62, 63, 64, 65]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M4-T6 — Replay Parity Gate

## Goal

Prove deterministic reconstruction is trustworthy enough to become the foundation for Timeline fork.

## Required verification

Use a long-lived Timeline with 20+ mixed logical commits covering structural/facet changes, relationship lifecycle, zero-effect Events, Work schedule/cancel/complete, Event+Work and Work-only commits, technical retry noise and Runtime reconstruction. Compare replay at multiple intermediate versions and current head against independently captured authoritative expectations on both adapters.

## Forbidden shortcuts

- No test-only authority path, replay-derived expected fixtures or normalization that hides semantic mismatches.
- Do not implement M5 fork inside this gate.

## Acceptance checklist

- [ ] current-head replay equals materialized authority;
- [ ] multiple intermediate versions reconstruct exact State/World Time;
- [ ] logical Pending Work matches each historical point;
- [ ] lease/fence/retry noise does not change logical reconstruction;
- [ ] restart and InMemory/PostgreSQL parity pass;
- [ ] one final candidate passes architecture/fmt/check/clippy/workspace tests/rustdoc/PostgreSQL integration;
- [ ] all M4 task records/issues agree.

## Completion evidence

- PR:
- merge SHA:
- final candidate:
- CI / PostgreSQL evidence:

## Progress log

- 2026-08-22 — Planned as M4 SERIAL GATE; closes last.
