# Loom V0 Developer Guide

This guide is a developer-facing navigation and workflow reference. It does not duplicate the architecture specification, repository Agent instructions, deployment runbooks or historical task plans.

## 1. Resolve architecture authority first

Before turning a baseline clause into an implementation requirement, read `docs/architecture/README.md`.

The Architecture Index defines:

- the canonical owner for each topic;
- document precedence;
- the reverse supersession table;
- the current accepted Amendments;
- deferred decisions.

Frozen baseline documents intentionally retain historical text. A sentence still present in a frozen document may have been superseded by an accepted Amendment.

Use this procedure:

```text
identify the relevant topic/clause
        ↓
open docs/architecture/README.md
        ↓
resolve canonical source + reverse supersession
        ↓
read every currently relevant accepted Amendment
        ↓
derive implementation requirements
```

If current canonical sources conflict, fix or escalate the documentation conflict before implementation. Do not choose whichever sentence is more convenient for the code change.

## 2. Architecture Amendment gate

A material semantic/authority/ownership/dependency/binding/time/scheduler/provenance change requires architecture treatment before implementation.

The current change procedure is owned by `docs/architecture/README.md` and follows the general shape:

```text
problem / counterexample
        ↓
Architecture Amendment
        ↓
affected-clause / authority-index update
        ↓
glossary update when terminology meaning changes
        ↓
implementation planning
        ↓
code
```

Do not maintain a copied list of accepted Amendments here. The Architecture Index is the current source.

A task note under `docs/tasks/` cannot introduce a new semantic or authority decision by itself.

## 3. Task context and execution state

`docs/tasks/` contains planning/audit material. GitHub Issues remain the collaboration surface, and the active orchestrator owns execution state and dependency scheduling.

When Multica coordinates work:

- Multica Issue state is the execution-state authority;
- Multica dependencies and Stage relationships decide readiness/order;
- task-note `status` / `depends_on` fields are documentary context only;
- stale Task Ledger metadata must not block a Multica-ready task.

Before implementing task-backed work:

1. read the active Issue/task context;
2. read the initiative/task note when it contains relevant scope, ownership or contract links;
3. confirm the planned scope still matches current architecture authority;
4. inspect current code/tests before editing.

For repository delivery completion, follow `docs/development/task-completion.md`.

Do not create a second post-merge workflow solely to reconcile Markdown with PR number, merge SHA or external status.

## 4. Cargo dependency and public-exposure governance

`docs/architecture/governance.md` is the authority for:

- crate dependency direction;
- public exposure rules;
- authority type placement;
- composition-root privileges.

Do not maintain a second full Cargo allowlist in this guide. Read the current governance document before adding or changing a workspace dependency edge.

The core ownership direction remains:

```text
semantic/public contracts
        ↓
Runtime-owned ports and execution authority
        ↓
concrete adapters implement those ports
        ↓
apps/loom-server wires the process together
```

Runtime must not gain a concrete Storage/transport dependency merely to make an implementation easier, and external consumers should use the public Loom surface rather than Runtime/Storage internals.

Useful governance checks include:

```bash
python3 tools/check_architecture.py
python3 tools/check_storage_sql_ownership.py
cargo deny check advisories bans licenses sources
```

Use `cargo metadata --format-version 1` when inspecting actual dependency edges.

## 5. Development and test procedures

Use `docs/development/README.md` as the development/testing index.

Important focused procedures include:

- `docs/development/postgres-tests.md` — PostgreSQL 18 + pgvector integration-test environment;
- `docs/development/runtime-worker.md` — worker/executor verification;
- `docs/development/task-completion.md` — repository delivery completion.

Choose verification based on the changed contract. A documentation-only edit should not automatically require every Rust/PostgreSQL lane, while Storage/SQL changes require PostgreSQL-aware verification.

The repository CI workflow remains the current source for CI path routing.

Multica failure notifications are opt-in. Include a standalone
`Multica-Issue: ME-123` line in the PR body before triggering PR CI. The shared
`.github/workflows/multica-ci-wakeup.yml` re-reads the PR and validates the open
PR/current-head Issue mapping before sending a failure notification.

PR lifecycle close intent is normalized by the repository's Multica PR metadata workflow; agents should not create a second manual bookkeeping flow around that metadata.

## 6. Public/API consumption

Applications should consume Loom through the public API surface instead of importing concrete Runtime or Storage internals as feature dependencies.

Useful reference consumers are:

- `crates/loom-client` — Rust HTTP client over `loom-api`;
- `apps/loom-cli` — command-line public consumer;
- `apps/loom-server` — privileged process composition root, not a model for ordinary application feature dependencies.

For the supported public workflow, use `docs/quickstart.md`.

For guidance on building upper-layer products on Loom, use `docs/application-development/README.md`.

## 7. Documentation placement

Use `docs/README.md` as the documentation category index.

| Category | Canonical location | Purpose |
| --- | --- | --- |
| Architecture authority | `docs/architecture/` + `docs/vision.md` + `docs/principles.md` | meaning, authority, invariants, accepted changes |
| Repository Agent instructions | `AGENTS.md` | repository-wide Agent guardrails |
| Application development | `docs/application-development/` | build upper-layer products on Loom without bypassing engine boundaries |
| Development/testing | `docs/development/` | how to build, test and verify the implementation |
| Deployment/runbooks | `docs/deployment/` | install, configure, operate, back up and troubleshoot Loom |
| Public/operator guidance | `docs/quickstart.md`, `docs/operator-guide.md` | consume and inspect the running engine |
| Implementation planning/history | `docs/tasks/` | optional task scope, dependency diagrams and evidence; not workflow-state authority |

Application-specific Agent instructions belong under that application (for example `apps/<name>/AGENTS.md`) rather than in a second repository-wide Agent guide tree.

Do not duplicate one workflow across categories. When a procedure moves, update the canonical guide and remove the obsolete alternative rather than preserving competing instructions.
