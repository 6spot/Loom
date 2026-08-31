# Application boundary

Use this guide to decide what an upper-layer Loom application may own.

## Application-owned concerns

An application may own:

- product UX and workflows;
- presentation and navigation;
- application-specific configuration;
- orchestration of public Loom operations;
- application caches or indexes that are explicitly derived/non-authoritative;
- external integrations unrelated to Loom's semantic authority.

## Loom-owned concerns

Do not move these into ordinary application feature code:

- semantic commit authority;
- Timeline logical ordering;
- World Time authority;
- Work lifecycle/claim semantics;
- Runtime Binding validation;
- Loom persistence internals;
- Loom SQL/migrations;
- concrete Storage implementation details.

For exact ownership rules, follow `docs/architecture/README.md` and the canonical document it resolves.

## Supported consumption shape

Prefer:

```text
application
   ↓
loom-api / loom-client / HTTP
   ↓
loom-server
```

Avoid:

```text
application
   ↓
loom-runtime / loom-storage / PgStorage / direct SQL
```

The main exception is a repository composition root whose explicit job is assembling the engine, such as `apps/loom-server`.

## Local application instructions

If an application needs development rules that do not apply repository-wide, place them under that application root, preferably in `apps/<name>/AGENTS.md` and `apps/<name>/docs/`.

Do not put one application's workflow into root `AGENTS.md` or Loom architecture documents.
