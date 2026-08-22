---
task: M7-T5
issue: 172
status: planned
depends_on: [150, 167]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M7-T5 — Scalable Pinned Read Boundary

- Pinned BaseWorldView means one TimelineVersion consistency, not mandatory full-World materialization.
- Runtime may use bounded lazy/cache/prefetch/version-fenced reads; every read is from pinned version or fails/retries before commit.
- Runtime owns storage/read ports + ReadSet; Capability receives no persistence authority.
- Candidate overlay still sees prior same-Resolution effects.
- PostgreSQL representative point/facet/relationship/event reads must demonstrate a non-full-snapshot path; InMemory may stay eager.
- Keep Timeline-wide CAS; do not introduce fine-grained commit validation in v0.
- Instrument rows/bytes/latency vs World size.

## Acceptance
- [ ] Concurrent commit cannot produce mixed-version view.
- [ ] Point read does not load whole PostgreSQL World.
- [ ] Overlay/ReadSet semantics remain correct.
- [ ] Restart/cache miss deterministic; benchmark evidence recorded.

Architecture: A0003 §4/§5.

## Verification evidence
Pending.