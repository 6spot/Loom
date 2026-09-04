---
task: C1-T2
issue: 491
status: completed
depends_on: [C1-T1]
created_at: 2026-09-04
started_at: 2026-09-04
completed_at: 2026-09-04
completion_pr: 510
merge_sha: 1a6fa8713dd6a14eb79a2f43cba8fb3c37a8a744
---

# Chronicle Rust Server and Studio Auth

## Canonical scope

GitHub Issue #491 is the executable specification.

## Goal

Establish the long-lived Rust Chronicle server, public/Studio API separation, and one environment-configured administrator while preserving C0 public behavior.

## Acceptance

- [x] Rust Chronicle server entry point exists and is documented.
- [x] public and Studio API namespaces are separated.
- [x] Studio authorization is enforced server-side from environment credentials.
- [x] credentials are never persisted or logged in plaintext.
- [x] C0 Timeline/Event/Entity/Search behavior remains covered or is explicitly migrated.
- [x] health/error/graceful-shutdown behavior is tested.
- [x] no Loom Runtime/Storage authority is moved into Chronicle.
- [x] applicable Rust/Chronicle CI passes.

## Progress Log

- 2026-09-04 — Planned under C1 Root #489. No implementation started.
- 2026-09-04 — Implementation added standalone Rust `apps/chronicle/server/` (Axum/Tokio), public `/api/v1/public/*` plus legacy `/v0/*` proxying to the preserved C0 read model, authenticated `/api/v1/studio/*`, compile-time embedded same-origin UI, typed errors, health/config validation and graceful shutdown. Compose runs Rust `chronicle-web` in front of the internal Python read sidecar; no Loom/SQL authority moved into Rust.
- 2026-09-04 — Review findings addressed: Docker web binding corrected, sensitive upstream/port config values redacted from errors, deterministic upstream readiness/first-contact checks added and deployment smoke rerun.
- 2026-09-04 — Delivery PR #510 merged as `1a6fa8713dd6a14eb79a2f43cba8fb3c37a8a744`. Exact delivery head `18360c8696b4454425c0be0859cf6aff6c4eba87` passed GitHub Actions Chronicle run 33856736453, Chronicle Docker run 33856736489, and CI run 33856736409. Catch-up post-merge reconciliation records the already-delivered task as completed on the canonical ledger.
