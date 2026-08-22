---
task: M11-T6
issue: 118
status: planned
depends_on: [114, 116, 117]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M11-T6 — Isolated Runtime Admin API

## Goal
Expose operator revision/provenance inspection and activation separately from ordinary World-facing API semantics.

## Required implementation
- Add architecture-approved `LoomAdminApi`/services for active/list/get revision, session provenance, EventRef producing session and compatible revision activation.
- Boundary exposes isolated `/admin/...` namespace with separate auth hook/policy.
- Admin reads/activation never create World Events/State.
- DTOs exclude Pg/Runtime authority tokens and secrets; add client/operator support only as required.

## Forbidden shortcuts
No activation through Action, raw pool/registry/ValidatedResolution exposure, secret return or World mutation.

## Acceptance checklist
- [ ] revision read/activation APIs work;
- [ ] session/Event provenance queries work;
- [ ] incompatible activation fails typed;
- [ ] Admin route/auth is distinct;
- [ ] activation leaves World history unchanged;
- [ ] architecture/fmt/check/clippy/tests/rustdoc/boundary integration pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after provenance linkage.
