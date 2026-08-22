---
task: M10-T1
issue: 187
status: planned
depends_on: [186]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
# M10-T1 — `loom-agency` contracts

- Define Agent references over Core Entity identity; no duplicate Core Agent hierarchy.
- Define AgentWorldView/context values, CognitiveRequest, Decision `Act(ActionInvocation)|NoAction`, CognitiveExecutor/Error, execution policy and audit-safe model/provider metadata.
- Keep Agency dependencies to approved lower layers; no Runtime/API/Storage/Boundary/vendor SDK.
- Executor can return Decision/error only, never Event/Effect/Resolution/ValidatedResolution/Commit authority.
- SPI must remain compatible with M5 coherent host topology without freezing one vendor runtime.

## Acceptance
- [ ] Decision cannot bypass normal Action authority.
- [ ] AgentWorldView differs from authoritative BaseWorldView.
- [ ] Metadata is provenance-ready and secret-free.
- [ ] Cargo DAG + standard gates pass.

Architecture: Amendment 0003 §§3.3–3.4.

## Verification evidence
Pending.