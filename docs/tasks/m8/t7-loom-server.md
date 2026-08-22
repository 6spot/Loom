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
- Add a production-oriented Linux multi-stage Dockerfile for `loom-server`; the runtime image contains only the server/runtime dependencies required to start Loom, not the Rust build toolchain.
- Add a root `compose.yaml` that deploys `loom-server` together with PostgreSQL 18 + pgvector, using a reproducibly pinned pgvector 0.8.x/PG18 image (currently `pgvector/pgvector:0.8.6-pg18`).
- Compose PostgreSQL uses a named persistent volume mounted at the PostgreSQL 18 image's supported data root, a `pg_isready` healthcheck, restart policy, and Loom-specific database/user defaults overridable through environment variables.
- `loom-server` receives its PostgreSQL connection/configuration through environment variables, waits for the database healthcheck before startup, exposes only the documented public server port, and has an explicit restart policy.
- Add `.env.example` with non-secret development/deployment defaults. Real passwords, provider credentials and other secrets must not be committed.
- The Docker/Compose path must run the same startup migration/config/revision/registry validation as `cargo run -p loom-server`; containers must not introduce a second initialization or authority path.

## Forbidden
No duplicate HTTP handlers, Runtime→PgStorage dependency, server-side semantic scheduler, hard-coded secrets, unbounded workers, disposable CI workflows, floating database major versions, or container-only semantic behavior.

## Acceptance
- [ ] `cargo run -p loom-server` starts in documented PostgreSQL 18 environment.
- [ ] `docker compose config` validates the committed deployment configuration.
- [ ] `docker compose up --build` starts PostgreSQL 18/pgvector and a healthy `loom-server` on Linux from a clean checkout plus documented `.env` configuration.
- [ ] PostgreSQL data survives `docker compose down` / subsequent `up` unless volumes are explicitly removed.
- [ ] `loom-server` does not start serving before PostgreSQL is healthy and startup validation/migrations succeed.
- [ ] No secret value is required to be committed to the repository; `.env.example` documents every required deployment variable.
- [ ] Restart resumes persisted World/Work/Ingress through the same Runtime/PgStorage authority path.
- [ ] Topology/shutdown/startup validation pass both natively and through the container entrypoint.
- [ ] CI hygiene + standard gates pass.

## Verification evidence
Pending.