# Agent implementation workflow

Use this guide after the task owner and scope are clear.

## 1. Inspect before editing

Before changing a file, inspect the current implementation and the nearby contract surface:

- callers and implementations;
- tests at the owning layer;
- public DTOs/traits when relevant;
- configuration and environment-variable parsing;
- persistence ports, SQL and migrations when relevant;
- current CI routing for the affected paths.

Search for actual references instead of inferring behavior from filenames or old documentation.

## 2. Define the smallest valid change

Write down the conceptual change before editing:

```text
owner
→ changed contract
→ implementation files
→ tests/evidence required
```

Stay inside the accepted task scope. If unrelated defects appear, record them separately unless they are required for a safe implementation.

Do not use a broad refactor as a substitute for understanding the owning contract.

## 3. Edit at the owning layer

Typical ownership reminders:

- `loom-core` describes World concepts;
- `loom-protocol` describes execution proposals;
- `loom-api` describes public consumption;
- `loom-capability` defines semantic extension SPI;
- `loom-agency` defines cognition/decision contracts;
- `loom-runtime` owns execution and semantic commit authority;
- `loom-storage` implements persistence ports and owns PostgreSQL details;
- `loom-boundary` adapts HTTP/JSON/SSE to `loom-api`;
- `loom-client` consumes the public HTTP surface;
- `apps/loom-server` is the process composition root;
- `apps/loom-cli` is a public consumer.

If the convenient solution requires moving authority to the wrong layer, redesign the implementation rather than forcing the dependency.

## 4. Do not duplicate mechanisms

Search before adding a new:

- API or DTO path;
- registry;
- Scheduler/worker path;
- initialization/bootstrap path;
- database access path;
- deployment configuration path;
- test harness.

Prefer one canonical path per workflow.

## 5. Treat failures as contract evidence

When a test fails, determine whether the defect is in implementation, test, environment, task assumptions or architecture.

Do not make tests pass by default through deletion, broad skipping, weaker assertions, hidden feature gates or bypassing PostgreSQL integration coverage.

If the task assumption is stale, correct the task/documentation source rather than encoding the stale assumption into code.

## 6. Environment variables

Before using, removing or renaming an environment variable, search for:

1. its parser/default;
2. Compose wiring;
3. tests;
4. current documentation;
5. historical references that should remain historical only.

Do not resurrect removed variables from old logs or previous Agent memory.

A variable listed in `.env.example` is not automatically passed to a Docker container; verify the rendered Compose configuration.

## 7. Documentation edits

Put durable information in the document category that owns it:

- architecture meaning/invariants → `docs/architecture/`;
- development/testing procedure → `docs/development/`;
- deployment/runbook procedure → `docs/deployment/`;
- public workflow → `docs/quickstart.md` / operator documentation as appropriate;
- implementation status/evidence → `docs/tasks/`;
- Agent procedure → `docs/agents/`.

Do not duplicate the same operational procedure across categories. Update the canonical guide and remove or redirect stale alternatives.

## 8. Review the complete diff

Before finishing, inspect the full diff for:

- unrelated changes;
- new dependency edges;
- accidental public API expansion;
- SQL outside Storage;
- duplicated configuration;
- stale comments or removed environment-variable names;
- skipped/disabled tests;
- documentation contradictions;
- missing task evidence.

Every changed file should have a clear reason to be part of the task.