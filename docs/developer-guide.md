# Loom V0 Developer Guide

This guide explains how the implementation task ledger, Architecture Index supersession lookup, Amendment gate and Cargo dependency DAG fit together so that an iteration can land without violating architecture authority. The normative source for each topic is `docs/architecture/README.md` (§1 authority table, §2 precedence, §3.1 reverse supersession, §6 change procedure).

## 1. Architecture Index supersession lookup (mandatory before any baseline clause becomes a task)

Frozen `world-runtime.md` / `runtime-contracts.md` / `implementation.md` files retain their historical text after Amendments 0001–0003. Do not convert a frozen clause into a task requirement without consulting the **reverse supersession table** in `docs/architecture/README.md` §3.1.

Procedure:

```text
identify frozen clause (e.g. core.md §8.4, world-runtime.md §8.1, runtime-contracts.md §14.11)
        ↓
locate exact row in index §3.1 (Affected sections → Current authority)
        ↓
read the cited Amendment section (e.g. Amendment 0001 §8.1 for Intent removal, Amendment 0003 §3.2 for Agency Wake target-specific compatibility)
        ↓
treat the Amendment + frozen index row as the current executable acceptance criteria, not the frozen sentence alone
        ↓
if the row is missing but a conflict is suspected, re-read all accepted Amendments' own affected-clause indices — then raise a doc defect rather than silently choosing a convenient sentence
```

Examples from the V0 baseline:

- `core.md §7.3 Trigger` → Amendment 0001 §8.2 (Trigger is umbrella; `Temporal Trigger = WorkSchedule::At`, Event Trigger = `Reaction → Immediate Work`).
- `world-runtime.md §8.1 / §2.4 / §13` → Amendment 0001 §9 + Amendment 0002 §2/§3 + Amendment 0003 §3.2/§5 (common claim/admission + target-specific Agency compatibility, chronology consumption as Timeline Logical State, end-of-document hard invariants are navigation aids not an independent spec layer).
- `implementation.md §19 CI baseline` → Amendment 0002 §4 (Ubuntu mandatory; macOS not mandatory).
- `runtime-contracts.md §16.5 pinned BaseWorldView` → Amendment 0003 §4 (consistency at the same logical snapshot position, not mandatory full eager materialization; version-fenced lazy / cache / prefetch allowed).

When a conflict is found, fix it in documentation first — never choose whichever sentence is convenient inside the implementation task.

## 2. Amendment gate

A material semantic/authority/ownership/dependency/binding/time/scheduler/provenance change requires an **Architecture Amendment** before code, per `docs/architecture/README.md` §6:

```text
problem / counterexample
        ↓
Architecture Amendment (with exact document + section locations it affects)
        ↓
update Architecture Index reverse supersession table
        ↓
update glossary if terminology/authority meaning changed
        ↓
re-plan implementation → code
```

Accepted amendments for V0 are:

- `docs/architecture/amendments/0001-runtime-liveness-and-boundaries.md` — bounded FailurePolicy, same-World-Time chronology budget, Scheduler driver ownership, SKIP LOCKED scope, Event occurred_at, Ingress, Template placement, terminology reconciliation.
- `docs/architecture/amendments/0002-supersession-and-authority-linkage.md` — exact supersession mapping, one claimability contract, Chronology Budget authority placement, CI baseline, missing-implementation observability, Amendment linkage rules.
- `docs/architecture/amendments/0003-agency-execution-and-pinned-read-boundary.md` — Agency Wake execution closure, target-specific admission, AgentWorldView production authority, scalable pinned reads, Timeline-wide commit serialization, scale deferrals.

An implementation task (`docs/tasks/...`) never introduces a new authority/semantic architecture by itself. If the work would require a new decision that belongs in the architecture authority map, stop and create an Amendment draft first.

## 3. Task-ledger workflow (one task, one file)

The implementation ledger is `docs/tasks/` (see `docs/tasks/README.md` for the full status-machine rules). Keep GitHub issues as the collaboration surface (assignment, checklists) and each `docs/tasks/<milestone>/...` file as the durable audit record.

### 3.1 Where to look

- Current V0 roadmap: `docs/tasks/v0-roadmap.md` (planned; supersedes unmerged M4–M13 from #60–#134).
- Milestone index: `docs/tasks/m12/README.md` (M12) etc.
- Cross-cutting validator initiative: `docs/tasks/validator/README.md`.
- Active task files: each begins with required YAML metadata:

```yaml
---
task: M12-T2
issue: 199
status: planned    # planned | in_progress | blocked | completed | cancelled
depends_on: [185, 198]
created_at: 2026-08-22
started_at:
completed_at:
completion_pr:
merge_sha:
---
```

Dates are `YYYY-MM-DD`; `completion_pr` and `merge_sha` are the GitHub PR number and integration-branch commit containing the completed work.

### 3.2 Lifecycle rules (condensed)

**Starting work** — in the implementation branch/PR, set `status: in_progress`, set `started_at`, and append a short Progress Log entry if the implementation scope differs from the original plan.

**Blocking work** — set `status: blocked`, explain the blocker/owner/unblock condition.

**Completing work** — completion requires **all** of: task-file acceptance checklist satisfied, `status: completed`, `completed_at` set, `completion_pr` and `merge_sha` recorded, verification evidence lists the relevant architecture/build/test/CI gates, and the GitHub issue is closed as completed with its checklist in agreement. Prefer updating the task record inside the completion PR; if the final merge SHA only exists after merge, add it immediately in a small follow-up audit commit/PR rather than leaving it blank permanently.

**Cancellation** — never mark cancelled/duplicate work as `completed`; record why and its replacement.

### 3.3 DAG and M12 ordering

```text
#179/#197 -> #198 loom-cli (SERIAL ROOT)
#185/#198 -> #199 V0 docs/quickstart       ← this task
#151/#192/#198 -> #200 neutral examples   (parallel Track 3, same stage)
#198/#199/#200 -> #201 rehearsal gate     (SERIAL GATE, last)
```

`#199` depends on `#185` (server/Admin provenance) and the completed `#198` CLI; it does not block `#200`, but `#201` cannot close until all three finish. Every M12 task must be exercisable through the formal public surface only (server/client/CLI).

## 4. Cargo dependency DAG

The DAG is mandatory for every crate, capability crate, adapter and application (`docs/architecture/governance.md` §4, `docs/architecture/implementation.md` §3–§4, summarized in `README.md`'s Rust workspace section). The enforcement is `python3 tools/check_architecture.py` (in CI) plus `cargo deny` and `check_storage_sql_ownership`.

### 4.1 Framework crate allowlist

```text
loom-protocol   -> loom-core
loom-api        -> loom-core, loom-protocol
loom-capability -> loom-core, loom-protocol
loom-agency     -> loom-core, loom-protocol
loom-runtime    -> loom-core, loom-protocol, loom-api, loom-capability, loom-agency
loom-storage    -> loom-core, loom-runtime
loom-boundary   -> loom-api
loom-client     -> loom-api
loom-validator  -> loom-api, loom-client
loom-bench      -> loom-api, loom-agency, loom-capability, loom-core, loom-protocol, loom-runtime, loom-storage
capabilities/*  -> loom-core, loom-protocol, loom-capability
cognitive-*     -> loom-core (if needed), loom-protocol (if needed), loom-agency
apps/loom-server -> loom-api, loom-runtime, loom-storage, loom-boundary  (+ installed extension/provider crates by path)
apps/loom-cli / loom-studio -> loom-api, loom-client
tests/loom-composition -> loom-api, loom-capability, loom-core, loom-neutral, loom-protocol, loom-runtime, loom-storage
```

Prohibited edges are deliberate:

```text
runtime <-> capability / agency / storage / boundary   (Runtime call direction may differ from Cargo direction)
runtime must not import axum/hyper/sqlx/pgvector/reqwest/tokio-postgres/tonic/tower
api/capability/agency/protocol/core must not import sqlx/postgres/axum/hyper/object_store/tower-http etc.
loom-storage is the only crate owning SQLx/PostgreSQL (migrations in crates/loom-storage/migrations/, runtime SQL in crates/loom-storage/sql/)
loom-validator must not import loom-core/protocol/capability/agency/runtime/storage/boundary/neutral/sqlx/axum/reqwest/object_store
```

### 4.2 Port ownership (governance §4.1)

The correct direction is: Runtime defines the persistence/registry/entropy ports it needs; `loom-storage` / concrete capability crates **depend on** and implement those ports; the application composition root (`apps/loom-server`) wires them together. Runtime therefore never depends on Storage concrete types; Capability never depends on Runtime.

### 4.3 How to verify

```bash
cargo metadata --format-version 1 | python3 -m json.tool   # inspect actual edges
python3 tools/check_architecture.py                         # DAG + forbidden externals
python3 tools/check_storage_sql_ownership.py                # SQL ownership + inline sqlx!()
cargo deny check advisories bans licenses sources
cargo check --workspace --all-targets --all-features
cargo clippy --workspace --all-targets --all-features -- -D warnings
```

### 4.4 `loom-cli` as a compliance example

`apps/loom-cli` (post-#276) is a reference for staying inside the DAG:

- Production dependencies only `loom-client` + `loom-api` (+ `clap`/`tokio`/`serde` helpers). No `loom-runtime`/`loom-storage`/`loom-capability`/`loom-boundary`/`PgStorage`.
- `loom-boundary`/`loom-runtime` appear only in `dev-dependencies` for boundary-driven integration fixtures (`loom-boundary` + `InMemoryStore` + `loom-neutral` via `loom-client` HTTP/SSE).
- `tools/check_architecture.py` explicitly allowlists `loom-client` for `loom-cli`.

## 5. Where to put documentation

`docs/README.md` separates the three categories:

| Category | Location | Answers | Example |
| --- | --- | --- | --- |
| **Architecture authority** | `docs/architecture/` + `docs/vision.md` + `docs/principles.md` | what Loom means, which layer owns an authority, invariants, how an Amendment supersedes baseline | `core.md`, `world-runtime.md`, `governance.md` |
| **Development / operations** | `docs/development/` | how to run or verify the current implementation (one current guide per workflow) | `loom-server.md`, `postgres-tests.md`, `runtime-worker.md`, plus the V0 guides added by M12-T2: `docs/quickstart.md`, `docs/operator-guide.md`, this file |
| **Deployment/runbook** | `docs/deployment/` (when the deployment path is implemented) | deployment procedures | planned |
| **Implementation audit trail** | `docs/tasks/` | scope/dependencies/status/evidence | `docs/tasks/m12/t2-v0-documentation.md` |

Do not duplicate one topic across categories. Architecture documents do not repeat operational commands; development guides do not redefine invariants; task files do not become long-lived runbooks. Preferred fix for competing instructions is deletion/replacement over accumulating compatibility notes.

## 6. Developing against M12-T2

When extending documentation or fixtures under this milestone:

- Implement against the post-#276 baseline (`55c8bf4` merge of `loom-cli`); treat `apps/loom-cli`'s pure-consumer contract as authoritative for examples.
- Coordinate with `M12-T3` (`capabilities/loom-neutral`, Templates): multiple Template revisions proving future-World-only changes and installed-but-disabled semantics are owned by that track — this guide references them generically without inventing a parallel Template fixture layout.
- Keep tests/docs green:

```bash
cargo fmt --all -- --check
cargo check --workspace --all-targets --all-features
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo deny check advisories bans licenses sources
python3 tools/check_architecture.py
python3 tools/check_storage_sql_ownership.py
cargo test -p loom-cli --all-features
bash tools/postgres-test.sh up && cargo test --workspace --all-features  # exercises postgres contracts where applicable
```

A new dependency edge, public exposure or authority type placement that is not in the allowlist must first be added to `docs/architecture/governance.md` via the Amendment procedure before landing.
