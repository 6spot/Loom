---
task: M13-T6
issue: 134
status: planned
depends_on: [66, 73, 80, 87, 94, 103, 111, 119, 127, 129, 130, 131, 132]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---

# M13-T6 — Final Loom Engine V0 Release Gate

## Goal
Prove V0 from a clean environment through public surfaces in one integrated scenario.

## Required end-to-end scenario
1. Start `loom-server` on clean PostgreSQL18+pgvector/object store with Runtime Revision R1 and neutral Templates.
2. Create Template-backed World and verify exact World Capability binding.
3. Submit idempotent Ingress/Action; commit Events/State + Reaction Work; observe SSE.
4. Kill before Work executes, restart and resume Work.
5. Query State, History, Scope, Entity/Relationship trajectories and causal graph.
6. Perform bounded semantic retrieval/blob access; rebuild vector projection and prove World authority unchanged.
7. Replay current/historical TimelineVersions and compare State/logical Pending Work.
8. Historical fork; diverge parent/child and prove isolation.
9. Activate R2; old sessions remain R1, new sessions pin R2.
10. Schedule deterministic Agent wake/cognition and route Act through normal Action authority.
11. Inspect complete Event→Session→Revision/executor/read/entropy/call provenance.
12. Stop/restart all services and prove durable World/Timeline/Event/State/Work/ancestry/Ingress/provenance.
13. Exercise key flows through `loom-cli`.

## Required final gates
- [ ] `python3 tools/check_architecture.py`;
- [ ] `cargo fmt --all -- --check`;
- [ ] `cargo check --workspace --all-targets --all-features`;
- [ ] `cargo clippy --workspace --all-targets --all-features -- -D warnings`;
- [ ] `cargo test --workspace --all-features`;
- [ ] `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps`;
- [ ] `cargo deny check`;
- [ ] fresh PostgreSQL18+pgvector/storage integration;
- [ ] black-box HTTP/SSE/restart plus replay/fork/property/resource/provenance/Agency suites.

## Forbidden shortcuts
No direct DB/Runtime substitute for E2E operations, skipped restart/historical fork/projection rebuild/revision switch/cognition, test-only authority semantics or V0 closure on partial/red evidence. Deterministic fake cognition is allowed; production LLM provider is not required.

## Completion evidence
- PR:
- merge SHA:
- final candidate SHA:
- CI / PostgreSQL / black-box evidence:

## Progress log
- 2026-08-22 — Planned as the final blocking Engine V0 release gate. #133 is explicitly excluded.
