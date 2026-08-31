# Agent authority and scope

Use this guide before deciding where or how to change Loom.

## 1. Start from current repository state

Do not use memory, previous Agent runs, old branches, historical Issues or old task text as repository authority.

Always start with the current checkout and current canonical documents.

At minimum read:

- `AGENTS.md`;
- `docs/agents/README.md`;
- `docs/development/README.md`;
- `docs/tasks/README.md`.

Then read the sources relevant to the current task.

## 2. Classify the change

Classify the request before editing. Typical owners are:

| Change | Primary place to inspect |
| --- | --- |
| World semantics / authority | `docs/architecture/` + `crates/loom-core` / owning semantic crate |
| Runtime / Scheduler / Timeline / Work | `crates/loom-runtime` |
| PostgreSQL / migrations / SQL | `crates/loom-storage` |
| Public service/DTO contract | `crates/loom-api` |
| Capability SPI / implementations | `crates/loom-capability`, `capabilities/` |
| Agency / cognition contracts | `crates/loom-agency` |
| HTTP/SSE transport | `crates/loom-boundary` |
| Rust HTTP consumer | `crates/loom-client` |
| CLI | `apps/loom-cli` |
| Process composition | `apps/loom-server` |
| Deployment | `docs/deployment/`, `compose.yaml`, `Dockerfile`, `docker/`, `.env.example` |
| CI | `.github/workflows/`, `tools/` |
| Task status/evidence | `docs/tasks/` |

A file location is not sufficient evidence by itself. Search callers, implementations, tests and configuration before deciding ownership.

## 3. Resolve architecture authority

For architecture-sensitive work, read `docs/architecture/README.md` first.

Use its authority map and reverse supersession table to determine the current contract. Frozen baseline text may be historical context after an accepted Amendment supersedes it.

Do not copy a static Amendment list into Agent instructions. Always read the current Architecture Index.

If two current canonical sources conflict, resolve the documentation conflict before implementation. Do not choose whichever sentence makes the code change easier.

## 4. Amendment gate

Stop implementation if the request requires a new decision about semantic authority, ownership, World Time, Timeline ordering, Scheduler authority, Logical Commit semantics, World Runtime Binding, Runtime Revision semantics, persistence authority, public exposure, dependency direction, replay/fork semantics or Agency execution ownership.

That class of change follows the Architecture Amendment procedure before code.

## 5. Preserve ownership boundaries

Ask these questions before editing:

- Who owns this state?
- Who is allowed to mutate it?
- Which layer owns the public contract?
- Which layer owns persistence?
- Is there already a canonical path for this behavior?

Prefer extending the existing authority over creating a parallel API, registry, scheduler, initialization path, persistence path, migration path or deployment path.

## 6. High-value invariants for Agent decisions

These are navigation rules, not a replacement architecture specification:

- semantic execution authority stays in Runtime;
- PostgreSQL implementation details stay in `loom-storage`;
- external consumers use the public Loom surface rather than Runtime/Storage internals;
- Cargo dependency edges are architecture-sensitive and must match current governance;
- task files are audit records, not long-lived specifications;
- deployment behavior comes from current deployment docs and current repository configuration.

When any of these appears ambiguous, follow the canonical owner rather than elaborating a new rule here.