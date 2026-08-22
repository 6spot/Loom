# Loom Architecture Index

> Status: **normative document authority map for Loom v0.**
>
> 本文不重复具体 Runtime/World 规则。它只回答三个问题：**哪份文档对什么主题有最终解释权、发生冲突时如何裁决、当前有哪些正式 Amendment / deferred decisions。**

## 1. Document authority

Loom 不再把多份“规则摘要”视为彼此独立的规范源。每个主题只有一个 canonical owner。

| Topic | Canonical source |
| --- | --- |
| Core primitives / admission / World mechanism | `core.md` |
| Product semantic layers / ownership | `layers.md` |
| World Runtime Binding / World Time / Logical Commit / Execution Session / scheduler chronology baseline | `world-runtime.md` |
| Detailed Runtime ↔ Capability execution protocol | `runtime-contracts.md` |
| Software evolution / Runtime Revision semantics | `evolution.md` |
| Rust dependency DAG / public exposure / authority type placement | `governance.md` |
| Technical realization / persistence / dependency choices | `implementation.md` |
| Cross-cutting vocabulary | `glossary.md` |
| Accepted changes to a frozen baseline | `amendments/*.md` in amendment-number order |

`principles.md` is explanatory philosophy, **not an independent numbered normative rule set**. `AGENTS.md` is an execution guardrail/index, **not an independent architecture specification**. Root `README.md` is a navigation/status surface.

## 2. Precedence

When two documents appear inconsistent, apply this order:

1. A later accepted Architecture Amendment overrides the exact baseline clauses it names.
2. For Rust dependency direction, public exposure and authority type placement, `governance.md` wins.
3. For a topic owned by one canonical document in the table above, that canonical document wins over summaries elsewhere.
4. `glossary.md` controls terminology only; it does not create Runtime authority by itself.
5. `implementation.md` may choose a realization only inside the semantic/authority constraints defined by the architecture documents.
6. `principles.md`, `AGENTS.md`, README summaries and examples never override canonical contracts.

A conflict must be fixed in documentation before implementation. Do not silently choose whichever sentence is convenient.

## 3. Frozen baseline and amendments

The Loom v0 World Runtime baseline was frozen at commit `a2238f05e649dc30ce21da1e1cb321bc2784e895`.

Accepted amendments are part of the baseline from their merge point onward:

- `amendments/0001-runtime-liveness-and-boundaries.md` — Work failure exit, same-World-Time liveness budget, scheduler driver ownership, `SKIP LOCKED` scope, Event occurrence-time ownership, Ingress contract, Template technical placement and terminology reconciliation.

A frozen document does not mean “never change.” It means changes are explicit, reviewable Amendments rather than silent edits that make history impossible to audit.

## 4. Open questions registry

Architecture-blocking open questions live **only here or in a referenced active Amendment**. Individual documents should not grow independent hidden TODO lists.

### Blocking before v0 re-planning

None, once all accepted Amendments listed above are merged.

### Deferred implementation decisions

These are intentionally not architecture blockers:

- exact numeric retry/backoff defaults;
- exact chronology budget numbers;
- exact Rust struct/function names where ownership is already fixed;
- PostgreSQL table names/index layout;
- scheduler poll cadence/worker count;
- exact public authorization model for Runtime Admin operations;
- dependency patch/minor versions not required by semantic compatibility;
- dynamic per-World Capability migration/hot-plug.

If one of these begins to affect semantic authority, replay/fork, deterministic ordering, World Binding or public contract ownership, promote it to an Architecture Amendment before implementation.

## 5. Non-goal taxonomy

Do not maintain one giant duplicated “things we do not do” list.

- semantic/runtime non-goals belong in the canonical semantic document for that topic;
- Rust dependency/exposure prohibitions belong in `governance.md`;
- implementation technology defaults/rejections belong in `implementation.md`;
- temporary deferred decisions belong in this index.

## 6. Change procedure

For a material architecture change:

```text
problem / counterexample
        ↓
Architecture Amendment
        ↓
update canonical source later when re-baselining is useful
        ↓
update glossary/index references if terminology or ownership changed
        ↓
re-plan implementation
        ↓
code
```

Do not edit Issues/tasks/code first and backfill architecture later.
