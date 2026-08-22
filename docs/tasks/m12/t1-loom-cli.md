---
task: M12-T1
issue: 198
status: planned
depends_on: [179, 197]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M12-T1 — Official `loom-cli`

- Pure consumer of formal HTTP client/loom-api; no Runtime/Storage/concrete Capability/PgStorage dependency.
- Commands for Catalog/Template/World/Action/State/History/trajectory/causality/fork/feed/Ingress/revision/provenance/Admin controls where authorized.
- Human + deterministic JSON output and meaningful exit/error mapping.
- Configurable URL/auth; no secrets.
- Server remains authority; local validation is UX only.
- Integration tests cover representative workflows.

## Acceptance
- [ ] Blocking V0 workflows usable through CLI.
- [ ] JSON IDs/cursors script-safe.
- [ ] Errors/exit codes meaningful.
- [ ] Feed/fork/provenance/Admin operations work.
- [ ] Architecture/integration + standard gates pass.

## Verification evidence
Pending.