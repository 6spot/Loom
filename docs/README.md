# Loom documentation

This directory separates **architecture authority**, **application-development guidance**, **development/testing procedure**, **deployment/runbooks**, **public/operator guidance**, and **implementation audit history**. Do not duplicate one topic across those categories.

## Where to look

### Architecture

Use [`architecture/README.md`](architecture/README.md) as the architecture authority map. It defines canonical sources, precedence, reverse supersession, accepted Amendments and deferred decisions.

Architecture documents answer questions such as:

- what Loom means;
- which layer owns an authority;
- which invariants implementations must preserve;
- how an accepted Amendment supersedes a frozen baseline clause.

[`vision.md`](vision.md) and [`principles.md`](principles.md) provide project intent and cross-cutting philosophy. They do not override the architecture authority map.

### Building upper-layer applications

Use [`application-development/README.md`](application-development/README.md) when building products on top of Loom.

These guides cover:

- application vs Loom ownership boundaries;
- World/Timeline/Entity/Facet/Event/Action modeling;
- when application logic is enough vs when a Capability is justified;
- public API integration and application-owned persistence;
- application-level testing.

Application-specific development instructions belong under the application itself, for example `apps/<name>/AGENTS.md` and `apps/<name>/docs/`.

### Public quickstart and operator reference

- Quickstart (start stack, Catalog/`WorldTemplateDescriptor`/World/Action/State/History/Relationship/blob/semantic, Ingress/feed, automatic Scheduler discovery/World Time, replay/fork, provenance, deterministic Agency via neutral fixture): [`quickstart.md`](quickstart.md)
- Operator guide (Installed vs Binding vs Assembly, World Time vs Platform Time, logical Work vs lease, head/quiescence/budget, missing implementation/terminalization, Revision/Session provenance, replay vs rerun, fork ancestry, Agent visibility/CAS resample): [`operator-guide.md`](operator-guide.md)
- Capacity envelope — measured V0 evidence, unproven claims marked deferred: [`capacity-envelope.md`](capacity-envelope.md)

### Development and testing

Use [`development/README.md`](development/README.md) for current developer-facing procedures such as local PostgreSQL services, integration tests, task completion and worker verification.

[`developer-guide.md`](developer-guide.md) is the developer reference for Architecture Index lookup, Amendment gating, Task Ledger workflow and Cargo dependency governance.

Development documents answer **how to build, test or verify the Loom implementation**. A workflow should have one current operational guide. When a procedure is replaced, update or remove the old guide rather than leaving competing instructions.

### Deployment and operations

Use [`deployment/README.md`](deployment/README.md) for supported deployment/runbook procedures.

Deployment guidance is split into focused guides for first installation, configuration, routine operations, backup/recovery, troubleshooting, security, and repository/runtime data layout.

Task planning or acceptance criteria are not substitutes for these operational guides.

### Tasks

Use [`tasks/README.md`](tasks/README.md) for the implementation task ledger and current initiatives/roadmaps.

Task files are durable audit records: scope, dependencies, status, progress and verification evidence. They are not architecture authority and should not become long-lived developer or deployment runbooks.

## Document precedence

For semantic or ownership conflicts, follow the precedence rules in [`architecture/README.md`](architecture/README.md). Operational/application guides must conform to the architecture but do not redefine it.

For repository Agent behavior, root [`../AGENTS.md`](../AGENTS.md) is the repository-wide instruction entry point. Application-specific Agent rules belong under that application, not in a second global Agent documentation layer.

Do not recover current commands from historical task records, closed issues, superseded documents or chat history.

## Maintenance rule

Prefer deletion or replacement over accumulating compatibility notes. If two current documents prescribe the same workflow differently, that is a documentation defect and should be resolved at the canonical source.
