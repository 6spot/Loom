# Loom V0 Developer Guide

This guide is a developer-facing navigation and workflow reference. It does not duplicate the architecture specification, Agent procedure, deployment runbooks or historical task plans.

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

An implementation task under `docs/tasks/` cannot introduce a new semantic or authority decision by itself.

## 3. Task Ledger workflow

`docs/tasks/README.md` owns the Task Ledger state model. GitHub Issues remain the collaboration surface; task files are the durable repository audit record.

Before implementing task-backed work:

1. read `docs/tasks/README.md`;
2. read the active initiative/milestone index when one exists;
3. read the concrete task file and linked Issue;
4. verify dependency eligibility on the default branch;
5. confirm the planned scope still matches current architecture authority.

For task completion, follow `docs/development/task-completion.md`.

A delivery PR merge is not by itself task completion. Required completion evidence must be reconciled into the canonical task record on the default branch before dependent work or external completion state advances.

Task files are audit records, not alternate architecture specifications or long-lived runbooks.

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
- `docs/development/task-completion.md` — task completion/reconciliation workflow.

Choose verification based on the changed contract. A documentation-only edit should not automatically require every Rust/PostgreSQL lane, while Storage/SQL changes require PostgreSQL-aware verification.

Agents additionally follow `docs/agents/verification.md`; the repository CI workflow remains the current source for CI path routing.

## 6. Public/API consumption

Applications should consume Loom through the public API surface instead of importing concrete Runtime or Storage internals as feature dependencies.

Useful reference consumers are:

- `crates/loom-client` — Rust HTTP client over `loom-api`;
- `apps/loom-cli` — command-line public consumer;
- `apps/loom-server` — privileged process composition root, not a model for ordinary application feature dependencies.

For the supported public workflow, use `docs/quickstart.md`.

## 7. Documentation placement

Use `docs/README.md` as the documentation category index.

| Category | Canonical location | Purpose |
| --- | --- | --- |
| Architecture authority | `docs/architecture/` + `docs/vision.md` + `docs/principles.md` | meaning, authority, invariants, accepted changes |
| Agent procedure | `AGENTS.md` + `docs/agents/` | how repository Agents work |
| Development/testing | `docs/development/` | how to build, test and verify the implementation |
| Deployment/runbooks | `docs/deployment/` | install, configure, operate, back up and troubleshoot Loom |
| Public/operator guidance | `docs/quickstart.md`, `docs/operator-guide.md` | consume and inspect the running engine |
| Implementation audit trail | `docs/tasks/` | task scope, dependency, status and evidence |

Do not duplicate one workflow across categories. When a procedure moves, update the canonical guide and remove the obsolete alternative rather than preserving competing instructions.
