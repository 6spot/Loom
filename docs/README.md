# Loom documentation

This directory separates **architecture authority**, **development/operations procedures**, and **implementation audit history**. Do not duplicate one topic across those categories.

## Where to look

### Architecture

Use [`architecture/README.md`](architecture/README.md) as the architecture authority map. It defines canonical sources, precedence, reverse supersession, accepted Amendments and deferred decisions.

Architecture documents answer questions such as:

- what Loom means;
- which layer owns an authority;
- which invariants implementations must preserve;
- how an accepted Amendment supersedes a frozen baseline clause.

[`vision.md`](vision.md) and [`principles.md`](principles.md) provide project intent and cross-cutting philosophy. They do not override the architecture authority map.

### Public quickstart, operator and developer guides

- Quickstart (start stack, Catalog/Template/World/Action/State/History, Ingress/feed, Scheduler/World Time, replay/fork, provenance, deterministic Agency): [`quickstart.md`](quickstart.md)
- Operator guide (Installed vs Binding vs Assembly, World Time vs Platform Time, logical Work vs lease, head/quiescence/budget, missing implementation/terminalization, Revision/Session provenance, replay vs rerun, fork ancestry, Agent visibility/CAS resample): [`operator-guide.md`](operator-guide.md)
- Developer guide (Architecture Index supersession lookup, Amendment gate, task-ledger workflow, Cargo DAG): [`developer-guide.md`](developer-guide.md)
- Capacity envelope — measured V0 evidence, unproven claims marked deferred: [`capacity-envelope.md`](capacity-envelope.md)

### Development

Use [`development/README.md`](development/README.md) for current developer-facing procedures such as local services, integration tests and repository workflows.

Development documents answer **how to run or verify the current implementation**. A workflow should have one current operational guide. When a procedure is replaced, update or remove the old guide rather than leaving competing instructions in another directory.

### Deployment

Deployment/runbook documentation belongs under `docs/deployment/` when the corresponding deployment path is implemented. Planning or acceptance criteria in a task record are not a substitute for an operational deployment guide.

### Tasks

Use [`tasks/README.md`](tasks/README.md) for the implementation task ledger and current V0 roadmap.

Task files are durable audit records: scope, dependencies, status, progress and verification evidence. They are not architecture authority and should not become long-lived developer or deployment runbooks.

## Document precedence

For semantic or ownership conflicts, follow the precedence rules in [`architecture/README.md`](architecture/README.md). Operational guides must conform to the architecture but do not redefine it.

For operational instructions, use the current guide in the appropriate `development/` or `deployment/` section. Do not recover current commands from historical task records, closed issues, superseded documents or chat history.

## Maintenance rule

Prefer deletion or replacement over accumulating compatibility notes. If two current documents tell a developer or agent to perform the same workflow differently, that is a documentation defect and should be resolved at the source.
