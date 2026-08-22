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
- Define one host-side Loom persistence root for the supported single-host deployment: `${LOOM_DATA_DIR:-./loom}`. All filesystem-backed durable data owned by the Compose deployment lives below this root; do not scatter authoritative/persistent state across Docker named volumes or unrelated host paths.
- Keep a stable subdirectory layout below that root. At minimum PostgreSQL uses `${LOOM_DATA_DIR:-./loom}/postgres`; the local Blob/Object-Store deployment uses `${LOOM_DATA_DIR:-./loom}/blobs`. Future filesystem-backed persistent adapters must receive their own documented child directory rather than creating another persistence root.
- PostgreSQL bind-mounts the Loom data subdirectory at the PostgreSQL 18 image's supported data root, uses a `pg_isready` healthcheck and restart policy, and has Loom-specific database/user defaults overridable through environment variables. `loom-server` must not receive direct filesystem access to PostgreSQL's raw data directory.
- The repository-local default `./loom/` is deployment/runtime data and must be gitignored. Production may override only the root through `LOOM_DATA_DIR`; the child layout remains stable so backup, restore and migration can operate on one Loom data tree.
- `loom-server` receives its PostgreSQL connection/configuration through environment variables, waits for the database healthcheck before startup, exposes only the documented public server port, and has an explicit restart policy.
- Add `.env.example` with non-secret development/deployment defaults including `LOOM_DATA_DIR=./loom`. Real passwords, provider credentials and other secrets must not be committed.
- The Docker/Compose path must run the same startup migration/config/revision/registry validation as `cargo run -p loom-server`; containers must not introduce a second initialization or authority path.

## Forbidden
No duplicate HTTP handlers, Runtime→PgStorage dependency, server-side semantic scheduler, hard-coded secrets, unbounded workers, disposable CI workflows, floating database major versions, container-only semantic behavior, Docker named volumes for Loom-owned persistent data, or persistent Compose data outside the configured Loom data root.

## Acceptance
- [ ] `cargo run -p loom-server` starts in documented PostgreSQL 18 environment.
- [ ] `docker compose config` validates the committed deployment configuration.
- [ ] `docker compose up --build` starts PostgreSQL 18/pgvector and a healthy `loom-server` on Linux from a clean checkout plus documented `.env` configuration.
- [ ] The default single-host deployment creates one repository-local `./loom/` persistence tree (or the configured `LOOM_DATA_DIR`) with stable `postgres/` and local `blobs/` children; `./loom/` is gitignored.
- [ ] PostgreSQL and every filesystem-backed persistent Loom component bind-mount only child paths under `LOOM_DATA_DIR`; no Docker named volume holds Loom-owned durable data.
- [ ] Persistent data survives `docker compose down` / subsequent `up`; deleting containers or Compose metadata does not delete the Loom data tree.
- [ ] `loom-server` does not start serving before PostgreSQL is healthy and startup validation/migrations succeed.
- [ ] No secret value is required to be committed to the repository; `.env.example` documents every required deployment variable, including the unified data root.
- [ ] Restart resumes persisted World/Work/Ingress through the same Runtime/PgStorage authority path.
- [ ] Topology/shutdown/startup validation pass both natively and through the container entrypoint.
- [ ] CI hygiene + standard gates pass.

## Verification evidence
Pending.