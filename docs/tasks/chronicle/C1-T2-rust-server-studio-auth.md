---
task: C1-T2
issue: 491
status: planned
depends_on: [C1-T1]
created_at: 2026-09-04
started_at:
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
