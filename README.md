# Loom

> **Loom lets you create worlds that keep living.**

Loom 是一个用于构建、运行和扩展**持续演化智能世界**的开放引擎。

Loom 不以 MiroFish 的工程结构为基础，也不追求对其实现兼容。MiroFish 只作为历史源码与设计参考保留在 Git 历史/上游仓库中；当前工作树从 Loom 自己的架构重新开始。

## Architecture first

先读 [`docs/architecture/README.md`](docs/architecture/README.md)。它是 Loom v0 的 **document authority map**，定义每个主题的 canonical source、冲突裁决顺序、reverse supersession table、accepted Amendments 与当前 deferred decisions。

关键文档：

- [`docs/architecture/README.md`](docs/architecture/README.md) — document authority / precedence / reverse supersession / amendment index
- [`docs/architecture/glossary.md`](docs/architecture/glossary.md) — canonical terminology
- [`docs/vision.md`](docs/vision.md) — 项目愿景
- [`docs/principles.md`](docs/principles.md) — cross-cutting philosophy，不再维护第二套编号规范
- [`docs/architecture/core.md`](docs/architecture/core.md) — Core conceptual closure
- [`docs/architecture/layers.md`](docs/architecture/layers.md) — 五层语义模型
- [`docs/architecture/world-runtime.md`](docs/architecture/world-runtime.md) — frozen World Runtime baseline
- [`docs/architecture/runtime-contracts.md`](docs/architecture/runtime-contracts.md) — detailed Runtime/Capability execution contract
- [`docs/architecture/evolution.md`](docs/architecture/evolution.md) — software/world evolution
- [`docs/architecture/governance.md`](docs/architecture/governance.md) — Cargo DAG / public exposure / authority placement
- [`docs/architecture/implementation.md`](docs/architecture/implementation.md) — technical realization baseline
- [`docs/architecture/amendments/0001-runtime-liveness-and-boundaries.md`](docs/architecture/amendments/0001-runtime-liveness-and-boundaries.md) — runtime liveness/boundary closure
- [`docs/architecture/amendments/0002-supersession-and-authority-linkage.md`](docs/architecture/amendments/0002-supersession-and-authority-linkage.md) — exact supersession mapping / authority linkage cleanup
- [`docs/architecture/amendments/0003-agency-execution-and-pinned-read-boundary.md`](docs/architecture/amendments/0003-agency-execution-and-pinned-read-boundary.md) — Agent Wake execution closure / scalable pinned-read semantics / Timeline concurrency clarification

建议阅读顺序：

```text
architecture/README + glossary
        ↓
vision + principles
        ↓
core + layers
        ↓
world-runtime
        ↓
all accepted amendments
        ↓
runtime-contracts + evolution
        ↓
implementation + governance
```

冻结 baseline 仍保留其历史原文。**在把任何 baseline 章节转成实现任务之前，必须先查 Architecture Index 的 reverse supersession table。** `AGENTS.md` 是开发执行入口，不是另一份架构规范。

## Core runtime distinctions

Loom v0 保持以下核心分离：

```text
Installed Capability
= platform software availability

World Runtime Binding
= one World's semantic enablement / compatibility contract

Execution Assembly
= exact software implementations pinned for one root Session
```

以及：

```text
World History
= committed Events + frozen Effects

Materialized World State
= Entity / Relationship / Facets

Timeline Logical State
= World Time / logical Work / logical ordering
  / Chronology Budget consumption / TimelineVersion / ancestry

Platform Operational State
= lease / fence / retry / worker bookkeeping

Execution Provenance
= Runtime Revision / Session / exact implementation / read/call evidence
```

两个核心 mutation law：

> **No semantic World State mutation without a committed Event.**
>
> **No Timeline logical-state mutation without a Runtime-owned Logical Commit.**

World Time 是显式 Timeline logical state；PlatformClock、Event timestamp、retry/backoff 都不能隐式推动它。

`BaseWorldView` 的 pinned 语义现在明确指“同一个 Timeline logical snapshot position”，而不是“每次 Resolution 必须把整个 World 全量装进一份新内存快照”。实现仍可先使用 eager snapshot，但大世界读路径允许通过 revision-keyed cache、bounded prefetch、version-fenced lazy read 或 miss/refill/restart 等方式演进，只要不混读 revision、不把 persistence authority 泄漏给 Capability/Agency。

## Accepted amendment closure

Amendment 0001 + 0002 + 0003 已把冻结后审查发现的 runtime/document/Agency execution closure 纳入当前 v0 contract：

```text
bounded Runtime FailurePolicy
same-World-Time Chronology Budget
Chronology Budget consumption = Timeline Logical State
Runtime-owned Scheduler / Timeline Driver
single logical authority with multi-worker CAS/fencing
SKIP LOCKED only across independent Timeline heads
one canonical Scheduler claim/admission contract
Runtime-stamped Event occurred_at
Ingress envelope -> normal Action authority path
World Template -> Runtime-owned ValidatedWorldBirthPlan
Intent / Trigger / Reaction / Actor / Agent terminology reconciliation
exact baseline supersession mapping
current CI baseline = Ubuntu mandatory; macOS currently deferred
TimelineBlockedOnMissingImplementation observability
Agent Wake = Scheduler-managed durable execution obligation
Runtime owns Agent-wake claim/session/provenance/commit orchestration
AgentWorldView built through Binding-checked Runtime mediation
Capability Work and Agency Wake use target-specific execution compatibility
pinned read consistency != mandatory complete eager materialization
successful v0 Logical Commits serialize at Timeline scope
fine-grained ReadSet commit validation remains deferred
historical checkpoint acceleration remains deferred
worker executor / Send-Sync topology is an explicit implementation-planning decision
```

特别地：

- automatic technical retry 必须有界；terminal `Dead/Cancelled` 必须经 Logical Commit；
- 同一 WorldInstant 的 Immediate/Reaction/Agency-Wake execution 达到 chronology budget 后停止自动推进，但**不能**借此越过 due Work 推进 World Time；
- chronology-budget consumption 与 logical Work completion 在同一个 Logical Commit 中记录/重建，不是 operational worker counter；total completion counter 是最低安全维度，causal/derivation depth 只能作为额外 policy dimension；
- `SKIP LOCKED` 可以帮助 worker 分配不同 Timeline 的 head，不能在同一 Timeline 内跳过 logical head；
- Scheduler common claim/admission 条件仍以 accepted Amendment 的 canonical contract 为准；Agency Wake 再应用其 target-specific Agency execution compatibility；
- Agent Wake 不把 `CognitiveExecutor` 塞进普通 Capability `WorkHandler`。Runtime claim due wake，建立 pinned Session，构造 subjective `AgentWorldView`，运行 cognition，然后让 `Decision::Act(ActionInvocation)` 回到 normal Capability authority path；
- cognition 可以很慢，但 Timeline commit transaction 必须短；stale/fenced-out cognition result 不能 commit，重复 cognition 只属于 at-least-once execution/provenance；
- Ingress 是可靠 external envelope，不再形成第二套 Capability handler hierarchy；
- v0 `ProposedEvent` 不拥有选择 occurrence World Time 的 authority，Runtime 使用 pinned World Time stamp committed Event；
- 同一 Timeline 上 root Action 可以在 admission 允许时并行 Resolve，但成功 Logical Commit 仍由 TimelineVersion/CAS 串行化；Scheduler-managed Work 还额外只允许 logical head 获得执行资格。

## Rust workspace

```text
Loom
├── crates/
│   ├── loom-core/        # World Language
│   ├── loom-protocol/    # Internal Execution Language
│   ├── loom-api/         # Public Consumption Language
│   ├── loom-capability/  # semantic extension API/SPI
│   ├── loom-agency/      # cognition/decision/context contracts
│   ├── loom-runtime/     # execution + validation + logical commit + scheduler/Agency orchestration authority
│   ├── loom-storage/     # persistence adapter implementing Runtime-owned ports
│   └── loom-boundary/    # transport adapter over loom-api
├── apps/                 # composition roots and Loom consumers
├── tools/                # architecture/verification tooling
└── docs/
```

这些 crate 是代码责任与依赖边界，不是微服务边界。v0 保持单体 Rust workspace。

最核心的工程规则仍然是：

> **Core describes what a World is. Protocol describes execution proposals. API describes how Loom is consumed. Runtime decides what becomes reality.**

> **Extension defines semantics; Loom owns exposure.**

完整 Cargo dependency/public exposure/authority placement 规则只以 `docs/architecture/governance.md` 为准，不在 README 再维护一份 allowlist。

## Current status — Loom Engine V0

**Architecture:** Frozen baseline + accepted Amendments 0001, 0002, 0003 are the normative V0 contract. See [`docs/architecture/README.md`](docs/architecture/README.md) for document authority and reverse supersession.

**Implementation history:** The V0 implementation ledger is `docs/tasks/v0-roadmap.md`. Its milestone labels record delivery history only; they are not runtime versions or compatibility contracts. The current runtime has one canonical V0 state model, and intermediate development states are not supported execution states. The post-M13 Validator authority-fix and public-surface evidence history is recorded separately under [`docs/tasks/validator-recert/`](docs/tasks/validator-recert/README.md).

**Current-main certification:** The historical M13 candidate and closure records below remain preserved audit evidence. Current-main V0 re-certification is in progress and remains **pending until T25**; the repository must not be described as V0 re-certified or as having a complete recertification root before that final gate.

**Historical M12/M13 delivery evidence (preserved):**

- `#198` `loom-cli` — completed (post-#276 baseline, `apps/loom-cli` over `loom-client`/`loom-api` only)
- `#199` V0 operator/developer documentation + quickstart — completed (post-#280 baseline, `docs/quickstart.md`, `docs/operator-guide.md`, `docs/developer-guide.md`, `docs/capacity-envelope.md`)
- `#200` neutral V0 examples and public workflow fixtures — completed (post-#281 baseline, `capabilities/loom-neutral` with counter/observer/relationship/blob/semantic + `examples/neutral-v0` Templates)
- `#201` public-consumer rehearsal gate — completed on the clean documented workflow
- `#202` integrated V0 release gate — completed on candidate `52905862f3c26a6fb4d9991da2aa9fe8cfd11bc2`, integrated by PR #283
- `#203` final task/Issue/evidence closure audit — checklist/status reconciliation and final metadata closure recorded on merged baseline `dca5463a341bcb4cde19a999eba8ef37e0ea60dd`

Detailed task ledger: [`docs/tasks/README.md`](docs/tasks/README.md) and `docs/tasks/m12/`. Each task file is the durable audit record; GitHub issues remain the discussion surface.

**How to start:** Follow [`docs/quickstart.md`](docs/quickstart.md) — start the stack, construct a `WorldTemplateDescriptor` JSON (or `examples/neutral-v0/templates/revision-1.json`) and create a World, invoke Actions (including `neutral.link.create`/`neutral.blob.attach`), inspect State/History/Catalog, submit Ingress, tail/resume the Change Feed, configure the Scheduler for the target World/Timeline and let it progress Work/World Time after restart, replay/fork, inspect Runtime Revision/Session provenance and run a deterministic Agency Wake via the neutral `deterministic.fake` fixture. No Runtime/Storage imports or direct database access are required; the public surfaces are `loom-server` HTTP/SSE, `loom-client` and `loom-cli`. Template discovery via `CatalogService` remains **not available at head** (no `CatalogSnapshot` Template field — see Supported vs deferred matrix).

## Supported vs deferred — V0 scope matrix

| Domain | V0 supported | V0 deferred / unproven |
| --- | --- | --- |
| **World model** | Create/Load World via caller-constructed `WorldTemplateDescriptor` (TemplateId + `TemplateCapabilityRequirement[]` semver + `initial_world_time`) → Runtime-validated `ValidatedWorldBirthPlan`; immutable `World Runtime Binding`; per-Timeline `TimelineVersion`, `World Time`, `Timeline Logical State`; two supported example Templates `examples/neutral-v0/templates/revision-1.json` / `revision-2.json` proving future-World-only changes and installed-but-disabled semantics | Dynamic per-World Capability migration / hot-plug; generic `Event Scope`; Template discovery via `CatalogService` (no `CatalogSnapshot` Template field at head) |
| **Execution** | `Action` invoke → `Resolution` → `ValidatedResolution` → Timeline CAS Logical Commit; `Reaction` → Immediate `Work`; bounded `FailurePolicy` and `TimelineBlockedOnMissingImplementation` with authorized terminalization | Fine-grained `ReadSet` commit validation beyond Timeline-wide CAS; historical checkpoint acceleration |
| **Scheduler** | Deterministic `(effective_due_world_time, logical_schedule_order)` ordering; head-of-line barrier; quiescence; `Chronology Budget` as Timeline Logical State; `SKIP LOCKED` only across independent Timeline heads; single-thread executor per worker process, multi-process via shared PostgreSQL; Scheduler runs only when `LOOM_SCHEDULER_WORLD_ID` + `LOOM_SCHEDULER_TIMELINE_ID` are set and the server is restarted/reloaded after World creation (default Compose has no target) | Exact numeric budget/retry defaults as invariants; multi-threaded shared-process Runtime topology; default Compose auto-progress without target |
| **Time** | `World Time` advances only via quiescent Runtime-owned Logical Commit; `Platform Time` (lease/retry `available_at`) never advances `World Time` | Implicit time mapping from wall clock / event timestamp |
| **Persistence** | PostgreSQL 18 + pgvector required (`crates/loom-storage` owns all SQL), migrations in `crates/loom-storage/migrations/`, `loom/blobs` object store for immutable blobs; version-fenced pinned reads (`PinnedWorldReadStore`) do not require full-World eager snapshot | Alternative DBs; large-World 10k+ entity production tuning beyond measured envelope |
| **API / transport** | Unified `loom-api` service traits (`WorldService`, `ActionService`, `QueryService`, `HistoryService`, `IngressService`, `SubscriptionService`, `CatalogService`, `AdminService`); `loom-boundary` HTTP/JSON + SSE; `loom-client` formal HTTP client; `loom-cli` pure consumer | WebSocket transport; second Capability handler hierarchy for Ingress |
| **Revision / provenance** | Immutable `Runtime Revision` ledger (`LOOM_RUNTIME_REVISION_ID` + `LOOM_CORE_BUILD_REF` publish, confirm, and activate), `Execution Session`/`Execution Assembly` per root execution, `Event→Session` linkage, `ReadSet`/call/entropy evidence; execution requires a confirmed active Revision and exact compatibility with the complete persisted World Binding | In-place World software mutation; automatic World rewrite on Revision activation |
| **Replay / fork** | Deterministic replay of committed Events + Logical Journal `World Time`/`Work`/`budget`; head fork and historical fork with ancestry-preserving branch-local `Pending` clone | Checkpoint-based acceleration; deep cross-branch merge |
| **Agency** | Scheduler-managed durable `Agency Wake` → `AgentWorldView` (visibility-limited, Binding-checked) → `CognitiveExecutor` → `Decision::Act|NoAction` → normal Capability authority; explicit `resample` vs `ReuseDeterministic` CAS policy (provenance-visible, measured in `loom-bench`); deterministic `deterministic.fake` fixture demonstrated via `examples/neutral-v0/workflows/agency.sh` and `tests/loom-composition/neutral_v0_workflows.rs` (no vendor credentials) | Default `loom-server` composition still uses `UnavailableCognitiveExecutor` (`loom-server` defaults to blocked Wake until a future adapter wires `with_cognitive_executor`); Real vendor LLM integration as required V0 path; `CognitiveExecutor` inside `WorkHandler` |
| **Scale / CI** | Measured V0 envelope documented in [`docs/capacity-envelope.md`](docs/capacity-envelope.md) and `docs/tasks/m11/t3-capacity-benchmarks.md` (see below); CI required baseline is `ubuntu-latest` (Linux); PostgreSQL 18 contract jobs use `pgvector/pgvector:0.8.6-pg18` | Larger-scale claims beyond measured envelope are **unproven / deferred**; macOS is not a required CI gate (may be reintroduced when justified) |

Older planning records remain historical audit material and do not define the current V0 runtime contract.

## Prerequisites at a glance

| Prerequisite | V0 baseline | Details |
| --- | --- | --- |
| OS | **Ubuntu/Linux** required; container is the supported deployment | `ubuntu-latest` is the mandatory CI baseline; macOS is not required/supported as a gate |
| Rust | **1.97.1** (`rust-toolchain.toml`, edition 2024) + bounded Tokio/Axum/SQLx | See `docs/architecture/implementation.md` §2 and `Cargo.toml` |
| Database | **PostgreSQL 18 + pgvector 0.8.6** (`pgvector/pgvector:0.8.6-pg18`) | Managed via `compose.yaml` / `compose.test-db.yaml`; schema DDL in `crates/loom-storage/migrations/`, runtime SQL in `crates/loom-storage/sql/` — other crates must not own SQL |
| Object store | **Local filesystem immutable blobs** at `${LOOM_DATA_DIR:-./loom}/blobs` (bind-mount to `/var/lib/loom/blobs` in Compose) | PostgreSQL bind-mount is `${LOOM_DATA_DIR}/postgres` → `/var/lib/postgresql`; no Docker named volume owns Loom data; see `docs/development/loom-server.md` |
| Migrations | **Repository-owned** `crates/loom-storage/migrations/` applied by `loom-server` at startup (connect → healthcheck → migrate → validate registry → confirm/activate Revision) | Never via manual SQL fixtures for user-facing setup; examples use public Template/API/CLI |
| Server config | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `LOOM_DATABASE_URL` (native), `LOOM_DATA_DIR`; non-secret `LOOM_BIND_ADDR`, `LOOM_RUNTIME_REVISION_ID` (`loom-server`), `LOOM_CORE_BUILD_REF`, worker lease/retry/poll, Runtime semantic/resource limits, HTTP limits | All have non-secret defaults in `.env.example`; `LOOM_SCHEDULER_WORLD_ID`/`LOOM_SCHEDULER_TIMELINE_ID` optional bounded worker target |
| Runtime Revision | Publish and confirm at startup from `LOOM_RUNTIME_REVISION_ID`+`LOOM_CORE_BUILD_REF`+installed manifests; activation is isolated Admin CAS (`AdminActivateRuntimeRevisionRequest` with `expected_generation`) | Execution without a confirmed active Revision is unavailable; a new compatible Revision affects only new Sessions, while history/Binding remain unaffected — see `docs/operator-guide.md` and `apps/loom-server/src/config.rs` |
| Templates | Caller-constructed `WorldTemplateDescriptor` JSON (`id`, `revision`, `capabilities[]`, `configuration`, `initial_world_time`) via `world create --template-json` / `--template-file`; or `CreateWorldFromTemplateRequest` with top-level `{"template": descriptor}` via `world create --request-file`; both validated Runtime-side into `ValidatedWorldBirthPlan`; World `Binding` is immutable after birth and not retained by the Template (no `CatalogSnapshot` Template discovery at head — see `crates/loom-api/src/lib.rs:1913`); two supported example Templates `examples/neutral-v0/templates/revision-1.json` / `revision-2.json` demonstrate future-World-only changes and installed-but-disabled semantics | Dynamic per-World Capability migration / hot-plug; generic `Event Scope` |
| CLI | **`apps/loom-cli`** — pure consumer of `loom-client` + `loom-api`; `cargo run -p loom-cli -- --help` | No `loom-runtime`/`loom-storage`/concrete Capability imports in production; JSON (`--output json`, compact) and human (`--output human`) modes; `LOOM_SERVER_URL`, `LOOM_BEARER_TOKEN`, `LOOM_ADMIN_TOKEN` via flags/env, no hard-coded secrets |

Local examples use only public surfaces; real vendor LLM credentials are never required for V0. Deterministic fake cognition is demonstrated via the neutral V0 fixture `examples/neutral-v0/workflows/agency.sh` and `tests/loom-composition/neutral_v0_workflows.rs` (`crates/loom-agency/src/testing.rs:DeterministicCognitiveExecutor` via `deterministic.fake`); `crates/loom-bench` also uses it for measured envelope; the default `loom-server` public composition still uses `UnavailableCognitiveExecutor` until a future adapter wires it. Provider credentials belong only to a reviewed provider adapter's application config, not this composition root.

Full prerequisite, server startup and configuration reference: `docs/quickstart.md` §1, `docs/development/loom-server.md`, `docs/development/postgres-tests.md`, and `.env.example`.

## Quickstart

```bash
cp .env.example .env
docker compose config
docker compose up --build
# In another terminal (global flags before subcommand):
cargo run -p loom-cli -- --output human catalog --help
cargo run -p loom-cli -- --output human world create \
  --template-json '{"id":"neutral.counter.v1","revision":1,"capabilities":[{"id":"neutral.counter","version":"^0.1.0"}],"configuration":{},"initial_world_time":0,"bootstrap_actions":[]}'
# After World creation, configure Scheduler target and restart for Work/World Time progress:
#   echo "LOOM_SCHEDULER_WORLD_ID=<world-id>" >> .env
#   echo "LOOM_SCHEDULER_TIMELINE_ID=<timeline-id>" >> .env
#   docker compose up -d --build loom-server
```

Complete public workflow (see [`docs/quickstart.md`](docs/quickstart.md) for every command with expected output):

`start stack` → `construct WorldTemplateDescriptor + create World` (via `examples/neutral-v0/templates/revision-1.json`) → `invoke Action` (including `neutral.link.create`/`neutral.blob.attach`) → `inspect State/History/Catalog` → `submit Ingress` → `tail/resume feed` (`--after`/`--limit` / `resume_from`) → `configure Scheduler (LOOM_SCHEDULER_WORLD_ID/TIMELINE_ID + restart) → progress Work/World Time` → `replay/fork` → `inspect Runtime Revision/Session provenance` → `deterministic Agency Wake via neutral fixture` → `restart and resume`.

## CLI and public surfaces

- **CLI:** `apps/loom-cli` (`loom` binary) — global flags `--output/--server/--admin-token` **before** subcommand (e.g. `loom --output human catalog --world-id …` → `cargo run -p loom-cli -- --output human catalog --world-id …`), then `catalog`, `world create`, `timeline inspect/fork`, `action invoke`, `facet get`, `history events/event/causes/effects/walk`, `trajectory entity/relationship`, `feed subscribe/tail`, `ingress submit/status`, `admin revision/session/timeline/work/agency/world-time`. Machine-readable IDs/cursors are deterministic; `ApiErrorCode` → exit codes 10–16; local UUID/JSON validation is UX-only — the server remains authority. Integration fixture coverage is in `apps/loom-cli/tests/integration.rs`; parameter sweep verified against `cargo run -p loom-cli -- <subcommand> --help`.
- **HTTP client:** `crates/loom-client` (`loom-client` crate) — formal caller of `loom-boundary` over `loom-api` contracts.
- **Server:** `apps/loom-server` — production-like composition root (healthcheck → migrate → validate registry → activate Revision → construct Runtime/Boundary/workers → bind `LOOM_BIND_ADDR`).
- **Neutral examples:** `capabilities/loom-neutral` — `neutral.counter` and `neutral.observer` plus `neutral.link.membership` (Relationship), `neutral.blob.reference` (Facet) and `neutral.counter.semantic` (semantic index) covering Entity/Relationship/Facet, Action/Event, cross-Capability dependency (`observer → counter`), `Reaction`/`Work` via the installed registry (see `capabilities/loom-neutral/src/lib.rs`); two Templates `examples/neutral-v0/templates/revision-1.json` / `revision-2.json` proving future-World-only changes and installed-but-disabled semantics; deterministic Agency via `deterministic.fake` fixture (`examples/neutral-v0/workflows/agency.sh`, no vendor secrets); semantic retrieval and blob references via `SemanticProjectionStore` / `BlobStore` (`tests/loom-composition/neutral_v0_workflows.rs`). All survive restart/replay/fork.

Operator concepts and developer procedures are documented separately:

- Operator guide: [`docs/operator-guide.md`](docs/operator-guide.md)
- Developer guide: [`docs/developer-guide.md`](docs/developer-guide.md)
- Capacity envelope (measured, not claimed): [`docs/capacity-envelope.md`](docs/capacity-envelope.md)

## Capacity envelope — measured, not claimed

Observed on the single-host aarch64 benchmark harness (`crates/loom-bench`, `2026-08-24`):

- Single-Timeline same-`WorldInstant` Works serialize head-ordered; ~1.3 ms for 1, ~5.4 s for 128 across `drive_timeline` loop (`serialization_verified=true`, `chronology_consumed==N`).
- Multi-Timeline independent CAS domains scale with timeline count but share single-thread executor contention (~592 ops/s at 1 → ~38 ops/s at 64).
- Pinned point reads are `O(1)`: InMemory `rows_read=1, bytes=16, cache_hits=9` for world sizes 1..4096; PostgreSQL point reads `rows_read=1, bytes=36, p50 2–7 ms` for sizes 1..256 via version-fenced one-row queries.
- Cognition CAS loss waste: default `Resample` pays 2× executor invocations per conflict (`discarded==fresh`), `ReuseDeterministic` pays 1× with explicit `Reused` provenance — both verified via armed `WorkTerminalization` CAS conflict.

All numbers are *observed evidence*, not architecture invariants. Larger-scale production claims remain **unproven / deferred** until measured under load. Full methodology, tables and reproduction commands: `docs/capacity-envelope.md` and `docs/tasks/m11/t3-capacity-benchmarks.md`.

## CI baseline

- **Required:** `ubuntu-latest` authoritative workflow (`.github/workflows/ci.yml`) — checks `cargo deny`, `check_architecture`, `cargo fmt/check/clippy/test/doc` and the `postgres-contract` matrix (PostgreSQL 18 + pgvector service, 8 contract suites). No disposable verifier workflows.
- **Not required:** macOS is not a mandatory V0 gate (Amendment 0002 §4, `implementation.md` §19 superseded). It may be reintroduced when cross-platform application/UI requirements justify it.
- **Path-aware:** Rust/config/migration/test/tool, Compose/Docker and workflow paths trigger expensive gates; Markdown/task-only changes correctly skip them.
