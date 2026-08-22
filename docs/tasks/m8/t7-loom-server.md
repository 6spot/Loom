---
task: M8-T7
issue: 180
status: planned
depends_on: [160, 171, 176, 178]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M8-T7 — `apps/loom-server` composition root

- Wire PgStorage/migrations, installed Capability registry, Runtime Revision, Runtime, Template source, PlatformClock, Entropy, BlobStore, Boundary, Scheduler and Ingress workers under M5 topology.
- Validate migrations/revision/registry/config before serving; fail fast.
- Structured tracing + graceful shutdown; no secrets in repo/logs.
- Application composes concrete adapters but makes no semantic next-Work decision.
- CI remains Ubuntu/Linux mandatory baseline and safely skips irrelevant expensive jobs for docs-only changes.

## Forbidden
No duplicate HTTP handlers, Runtime→PgStorage dependency, server-side semantic scheduler, hard-coded secrets, unbounded workers or disposable CI workflows.

## Acceptance
- [ ] `cargo run -p loom-server` starts in documented PostgreSQL environment.
- [ ] Restart resumes persisted World/Work/Ingress.
- [ ] Topology/shutdown/startup validation pass.
- [ ] CI hygiene + standard gates pass.

## Verification evidence
Pending.