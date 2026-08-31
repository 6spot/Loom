# Loom application development

This directory explains how to build **upper-layer applications on Loom** without turning application code into another Runtime or Storage implementation.

It is for human developers and coding Agents building products such as Chronicle.

## Read by task

- [`application-boundary.md`](application-boundary.md) — what belongs in an application and which Loom surfaces it may consume.
- [`world-modeling.md`](world-modeling.md) — how to map an application domain onto World, Timeline, Entity, Facet, Event and Action concepts.
- [`capability-decision.md`](capability-decision.md) — when application logic is enough and when a reusable Loom Capability is justified.
- [`integration.md`](integration.md) — how applications communicate with a running Loom deployment and where application-owned data may live.
- [`testing.md`](testing.md) — recommended application-level verification strategy.

## Core rule

An upper-layer application **uses Loom; it does not bypass Loom**.

Ordinary application feature code should consume the public Loom contract through `loom-api`, `loom-client`, CLI/HTTP surfaces as appropriate. It should not use `loom-runtime`, `loom-storage`, `PgStorage`, SQL tables or concrete Capability implementations as its product feature surface.

`apps/README.md` and `docs/architecture/governance.md` remain authoritative for repository dependency/public-exposure rules.

## Application-specific instructions

Each substantial application may add its own local `AGENTS.md` and `docs/` under its application root, for example:

```text
apps/example/
├── AGENTS.md
├── README.md
├── docs/
└── ...
```

The local `AGENTS.md` should contain only application-specific rules. The repository root `AGENTS.md` remains the repository-wide Agent instruction file.
