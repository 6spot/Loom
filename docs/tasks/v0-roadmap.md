# Loom Engine V0 Roadmap — M4 through M13

Baseline: `main` at `55766947cdb68bce218c917ebb949872ed796fd6` after Milestone 3 closure.

This file is the durable execution roadmap for the remaining Engine V0 work. GitHub issues are the collaboration surface; `docs/tasks/<milestone>/` records are the repository audit trail. Unless a task is explicitly marked parallel-safe, execute tasks serially. Even parallel-safe work starts only after the milestone root contract is merged.

## Milestones

| Milestone | Parent | Final gate | Purpose |
| --- | ---: | ---: | --- |
| M4 | #60 | #66 | deterministic replay + logical Work history |
| M5 | #67 | #73 | Timeline ancestry + current/historical fork |
| M6 | #74 | #80 | Event Scope + full Catalog + trajectories + causal graph |
| M7 | #81 | #87 | Reaction atomicity + controlled entropy + scheduler |
| M8 | #88 | #94 | pgvector semantic projection + immutable blob foundation |
| M9 | #95 | #103 | durable Ingress + Change Feed + HTTP/SSE + `loom-server` |
| M10 | #104 | #111 | World Template + per-World Capability assembly/bootstrap |
| M11 | #112 | #119 | Runtime Change Ledger + Execution Provenance |
| M12 | #120 | #127 | Agent-local cognition + durable Agent wake |
| M13 | #128 | #134 | CLI + hardening + final V0 release gate |

## Default execution discipline

1. Merge the milestone SERIAL ROOT before downstream implementation.
2. One implementation task maps to one GitHub issue, one task record and normally one implementation PR.
3. `planned` becomes `in_progress` only when implementation starts.
4. Architecture ambiguity is resolved in normative docs/contracts before code; Codex must not invent authority, Cargo or public-exposure changes to make implementation convenient.
5. SERIAL GATE tasks run only after all blocking children are complete and must not become catch-all feature PRs.
6. Every later task inherits the architecture checker, fmt, check, clippy, workspace tests and rustdoc gates; storage/server milestones additionally inherit PostgreSQL 18/pgvector/restart contracts as relevant.
7. M13-T5 / #133 (`loom-studio` Native preview) is explicitly non-blocking for Engine V0. GPUI Web and production LLM providers are post-V0 concerns.

## Engine V0 completion definition

Engine V0 is complete only when #134 proves from a clean environment, primarily through public surfaces: Template-backed World birth, per-World Capability enforcement, Action/Ingress execution, Event/State authority, Reaction/Durable Work restart, SSE feed, history/trajectory/causality, semantic retrieval and blob access, deterministic replay, historical fork/isolation, Runtime Revision/provenance, deterministic Agent cognition, CLI consumption, full restart persistence and all quality/resource gates.

## Explicit non-goals for this roadmap

Rich production domain Capabilities, distributed/microservice architecture, Kafka/Redis/NATS, a dedicated graph/vector database, dynamic WASM plugin ABI, production multi-provider LLM integrations, large-scale sharding/performance work and stable GPUI Web are not Engine V0 blockers.
