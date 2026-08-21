# Milestone 3 Task Index — World Lifecycle + Resumable Runtime

Parent issue: #47

Baseline: Milestone 2 completed on `main` at `e9fde033fe375f9e03f20ef82d37f466e4ff1db2`. PostgreSQL 18 is already the authoritative Runtime persistence adapter; this milestone adds World/bootstrap lifecycle and proves Runtime compute can stop and resume from that authority without a second write path.

## Dependency graph

```text
#48 M3-T1  Public World creation + Runtime lifecycle/identity ports + InMemory
   ↓
#49 M3-T2  PostgreSQL lifecycle persistence hardening/integration
   ↓
#50 M3-T3  PostgreSQL restart/reload/resume vertical slice
   ↓
#51 M3-T4  final lifecycle/resumability parity gate
```

## Status

| Task | Issue | Status | Record |
| --- | ---: | --- | --- |
| M3-T1 World creation contract | #48 | completed | `t1-world-creation-contract.md` |
| M3-T2 PostgreSQL lifecycle persistence | #49 | completed | `t2-postgresql-lifecycle.md` |
| M3-T3 restart/reload/resume | #50 | completed | `t3-restart-resume.md` |
| M3-T4 final parity gate | #51 | completed | `t4-lifecycle-final-gate.md` |

## Milestone completion rule

The parent issue #47 may close only when every row above is `completed`, every child issue is closed as completed, and the final gate records one final candidate SHA with green architecture, formatting, build, clippy, workspace tests, rustdoc, PostgreSQL lifecycle contracts and restart/resume coverage.

## Scope guard

This milestone creates one World plus its initial Timeline through the unified Loom API and proves durable continuation across Runtime reconstruction. It does **not** add Timeline fork/ancestry, replay tooling, causal graph query API, semantic/vector retrieval, HTTP/SSE/WebSocket, CLI/Studio, World Template semantics or provider/LLM integration.

## Administrative notes

- 2026-08-21: M3 #47 created from the first remaining implementation-baseline gap after M2: public World creation and resumable Runtime authority.
- 2026-08-21: M3-T1 #48 started from M2 closure baseline `e9fde033fe375f9e03f20ef82d37f466e4ff1db2`.
- 2026-08-21: M3-T1 implementation candidate `76002e1170b68cf122ff8c9bec409b7ece3bbe85` passed clean standard CI `32488685071`; final task-record head `ca4bb8da00357773f124fdf2040b1b69b20a2af3` passed CI `32489003271`; implementation PR #52 merged as `76f880ce2b24b93eaa723aa3e8351b5aca29becc`; audit PR #53 merged as `02527ee48a7a08cc4c508c19512fa38155746ea5`.
- 2026-08-21: M3-T2 #49 started from T1 audit main `02527ee48a7a08cc4c508c19512fa38155746ea5`; scope is dedicated PostgreSQL lifecycle hardening/integration and explicit CI coverage.
- 2026-08-21: M3-T2 clean candidate `82003c734345e8bb8a01daa56409528acb6be7d9` passed standard CI `32490627476`; final task-record head `414d64750a0659b1d16d289b9b2d51fe0c4d6145` passed CI `32491281507`; implementation PR #54 merged as `2eb260e0eab1d72a2e1384ee7a7ae9ae6580e133`. Post-merge audit marks T2 completed. Repository workflow inventory contains only the long-lived `.github/workflows/ci.yml`; no temporary apply/verifier workflow remains.
