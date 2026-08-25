---
task: M10-T1
issue: 187
status: completed
depends_on: [186]
created_at: 2026-08-22
started_at: 2026-08-24
completed_at: 2026-08-24
completion_pr: 242
merge_sha: 0a1536155c426787415c907ca78ecee952b7ba59
---
# M10-T1 — `loom-agency` contracts

- Define Agent references over Core Entity identity; no duplicate Core Agent hierarchy.
- Define AgentWorldView/context values, CognitiveRequest, Decision `Act(ActionInvocation)|NoAction`, CognitiveExecutor/Error, execution policy and audit-safe model/provider metadata.
- Keep Agency dependencies to approved lower layers; no Runtime/API/Storage/Boundary/vendor SDK.
- Executor can return Decision/error only, never Event/Effect/Resolution/ValidatedResolution/Commit authority.
- SPI must remain compatible with M5 coherent host topology without freezing one vendor runtime.

## Acceptance
- [x] Decision cannot bypass normal Action authority.
- [x] AgentWorldView differs from authoritative BaseWorldView.
- [x] Metadata is provenance-ready and secret-free.
- [x] Cargo DAG + standard gates pass.

Architecture: Amendment 0003 §§3.3–3.4.

## Verification evidence
Closure audit evidence: the M13-T1 integrated candidate and its required Linux/PostgreSQL18+pgvector, property/fault, replay/fork, scheduler, provenance, Agency, black-box, CLI, docs, architecture, format, check, clippy, test, rustdoc, dependency/security and capacity gates passed; final integration merge 19c797d3e1e8bd20a21cda419789793623c5ca1f contains this evidence.