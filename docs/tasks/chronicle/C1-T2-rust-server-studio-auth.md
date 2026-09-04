---
task: C1-T2
issue: 491
status: in_progress
depends_on: [C1-T1]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at:
completion_pr:
merge_sha:
---

# Chronicle Rust Server and Studio Auth

## Canonical scope

GitHub Issue #491 is the executable specification.

## Goal

Establish the long-lived Rust Chronicle server, public/Studio API separation, and one environment-configured administrator while preserving C0 public behavior.

## Acceptance

- [ ] Rust Chronicle server entry point exists and is documented.
- [ ] public and Studio API namespaces are separated.
- [ ] Studio authorization is enforced server-side from environment credentials.
- [ ] credentials are never persisted or logged in plaintext.
- [ ] C0 Timeline/Event/Entity/Search behavior remains covered or is explicitly migrated.
- [ ] health/error/graceful-shutdown behavior is tested.
- [ ] no Loom Runtime/Storage authority is moved into Chronicle.
- [ ] applicable Rust/Chronicle CI passes.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Implementation started: standalone Rust crate
  `apps/chronicle/server/` (Axum/Tokio, own workspace following the
  C1-T1 `control_plane` precedent; no `loom-*`, SQLx/PostgreSQL driver, or
  inline SQL per governance). Public `/api/v1/public/*` + legacy `/v0/*`
  proxy to the preserved C0 Python read model (single historical read
  authority); Studio `/api/v1/studio/*` requires server-side Basic auth
  from `CHRONICLE_ADMIN_USER`/`CHRONICLE_ADMIN_PASSWORD` (fail-closed 503
  when unconfigured); same-origin web UI embedded at compile time;
  typed C0-compatible errors, health endpoint, graceful shutdown, and
  26-test coverage (unit + live-router integration). No C1-T1 coupling:
  control-plane tables are untouched, so this leaf builds in parallel
  without consuming C1-T1 outputs. Migration boundary documented in
  `apps/chronicle/docs/server.md`; Compose runs Rust `chronicle-web`
  fronting internal C0   `chronicle-read` sidecar.
- 2026-09-04 — Reviewer FAIL addressed: D-1 `CHRONICLE_BIND=0.0.0.0` in the
  Compose web service (full Docker stack rerun: web healthy and reachable);
  D-2 raw `CHRONICLE_UPSTREAM_URL`/`CHRONICLE_PORT` redacted from config
  errors plus regression tests; D-3 deterministic Python upstream readiness
  and first-contact proxied check in the front smoke (PG18 contracts and
  full Docker assertions rerun green locally).
