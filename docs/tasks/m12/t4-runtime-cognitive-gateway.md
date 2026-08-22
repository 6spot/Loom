---
task: M12-T4
issue: 124
status: planned
depends_on: [115, 116, 122, 123]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M12-T4 — Runtime CognitiveExecutor Gateway

## Goal
Execute cognition through injected Agency SPI with pinned context/session and a deterministic fake executor.

## Required implementation
- Runtime accepts injected CognitiveExecutor/provider registry only through Agency contract; concrete provider belongs at composition root.
- Start cognition execution session/revision before context/executor call.
- Pass only Agency request/context/policy values.
- Record executor/provider/model identifiers and context read/entropy/semantic evidence in provenance.
- Deterministic fake supports scripted Act/NoAction/error and separates technical failure from NoAction.

## Forbidden shortcuts
No vendor SDK in Runtime/Agency, raw WorldStore/BaseWorldView/CommitStore to executor, fake-executor hidden mutation or unpinned reads.

## Acceptance checklist
- [ ] fake executor runs through SPI;
- [ ] context/revision are pinned;
- [ ] executor/read evidence persists;
- [ ] NoAction vs technical failure is distinct;
- [ ] concurrent cognition sessions isolate state;
- [ ] architecture/fmt/check/clippy/tests/rustdoc pass.

## Completion evidence
- PR:
- merge SHA:
- verification:

## Progress log
- 2026-08-22 — Planned after context boundary.
