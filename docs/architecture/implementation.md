# Loom v0 Technical Foundation

> Status: **FROZEN technical baseline aligned with the Loom v0 World Runtime architecture.**
>
> 本文定义 Loom v0 的实现技术基线：Rust 工程层级、Cargo 依赖方向、基础依赖、统一 Public API、数据权威、持久化、运行环境、UI 与默认禁止项。领域语义仍由 Capability 定义；Core 概念边界以 `core.md` 为准；World Runtime Binding / World Time / Scheduler chronology / Execution Session 交叉闭包以 `world-runtime.md` 为准；详细执行语义以 `runtime-contracts.md` 为准；**Rust 依赖和公开能力治理以 `governance.md` 为强制规范**。

## 1. Implementation Principle

> **Implement Loom from the Loom architecture; do not translate MiroFish module-by-module.**

MiroFish 的旧 Python/Vue 实现不再作为 Loom 的工程骨架，也不作为兼容目标。需要参考具体算法、交互或实现思想时，可以查看 Git 历史或上游源码；Loom 不为旧接口、旧流程或旧数据模型保留兼容层。

Loom v0 采用 Rust 独立实现。

同时必须区分四张不同的图：

```text
Semantic ownership
Runtime call flow
Cargo dependency direction
Authority / persistence domains
```

它们不能相互代替。运行时 A 调用 B，不等于 Cargo 必须 `A -> B`；两项数据都持久化，也不代表它们属于同一种 World Truth。

特别冻结：

```text
Global Capability Registry
= installed software availability

World Runtime Binding
= target World semantic enablement / compatibility contract

Execution Assembly
= exact software implementations pinned for one Session
```

这三个概念不得再合并成一个全局 Registry mental model。

同样冻结：

```text
Semantic Work due-ness
= logical status + effective due World Time

Operational claimability
= retry / lease / worker / implementation availability

Scheduler chronology
= persistent same-Timeline logical order
```

平台运行条件不能替代 Timeline chronology。

---

## 2. Version Policy

Loom 不机械追逐所有依赖的 `latest`，也不长期停留在过时版本。

默认规则：

1. 有官方 LTS 的基础组件：采用最新仍受支持的 LTS；
2. 没有 LTS 的组件：采用最新稳定版本；
3. Rust toolchain、关键框架与快速演进依赖必须可复现地锁定；
4. 应用/workspace 仓库提交 `Cargo.lock`；
5. 依赖升级属于 Runtime / Platform Change，不属于 World History；
6. 升级不得静默改变已提交 World Event；
7. 新 Runtime Revision 只能为一个 World 选择满足其 Runtime Binding 的 compatible Capability implementations。

当前 v0 基线：

```text
Rust             1.97.1
Edition          2024
Tokio            1.51.x LTS
PostgreSQL       18
SQLx             0.9.x
Axum             0.8.x
pgvector         v0.8.x PostgreSQL extension / matching Rust integration
GPUI             pinned Zed revision, not floating main
```

Rust 本身没有 Java 风格的 LTS 发布线，因此使用明确的 stable toolchain 版本，而不是模糊的 `stable`。

---

## 3. Rust Implementation Layers

Loom 的产品/世界概念仍然使用：

```text
Core
Capability
World Template
World
Application
```

`World Runtime Binding` 不是第六个产品层；它是 World-level runtime metadata。

Rust 物理实现采用独立 dependency architecture：

```text
L0  Kernel
    loom-core

L1  Internal Execution Protocol
    loom-protocol

L2  Public / Extension Contracts
    loom-api
    loom-capability
    loom-agency

L3  Engine
    loom-runtime

L4  Adapters
    loom-storage
    loom-boundary
    concrete Capability implementations
    cognitive/provider adapters

L5  Applications / Composition Roots
    loom-server
    loom-cli
    loom-studio
```

这些层是代码责任和编译依赖边界，不是微服务边界。v0 保持单体 Rust workspace，不为了未来规模提前拆服务。

### 3.1 `loom-core` — World Language

负责：

```text
World / Timeline primitives
strong identities
World Time value types
Entity / Relationship structural mechanism
Facet ownership mechanism
Event ordering/association primitives
minimal mechanical WorldEffect
hard World invariants
```

Core 不承担“共享 DTO”职责。一个类型被多个 crate 使用，不代表它应该进入 Core。

World Time 的**值机制**属于 Core language；AdvanceWorldTime 的 Runtime authority/control type 不因为使用 `WorldInstant` 就自动属于 Core。

### 3.2 `loom-protocol` — Internal Execution Language

负责 Runtime / Capability / Agency 之间共享的、**尚未获得 Runtime authority** 的执行协议，例如：

```text
ActionInvocation
Resolution
ResolveOutcome
Rejection
ProposedEvent
NewWork / WorkMutation
shared execution query/value specifications
```

Protocol 只描述“组件提出/交换了什么”，不决定它能否成为 World Truth。

Capability `Resolution` 不拥有 World-Time advancement authority，也不拥有 scheduler ordering authority。

### 3.3 `loom-api` — Public Consumption Language

负责 Loom 对 Application、Transport、SDK 暴露的统一消费 contract，例如：

```text
World
Timeline
Action
Query
History
Subscription
Capability Catalog / Discovery
Runtime / Timeline Control and Administration where authorized
```

它是一个 contract crate，不是 HTTP crate。HTTP/CLI/GPUI 都只是它的消费者或 adapter。

API 可以暴露 stable World Binding/Template descriptors，但不得为了复用内部对象泄漏 Capability resolver、Runtime authority token、scheduler claim token 或 persistence model。

### 3.4 `loom-capability` — Semantic Extension API/SPI

负责 Capability manifest、definition、resolver/invariant/work/reaction SPI，以及 Resolver 所需的 host-facing port（例如 `ResolutionContext`）。

它依赖 Core/Protocol，但不依赖 Runtime。

`ResolutionContext` 只暴露受控 World reads/subresolution/Entropy 等明确能力；不暴露 PlatformClock、World-Time mutation、scheduler control、raw network/provider、Storage 或 Commit。

### 3.5 `loom-agency` — Agency Extension API/SPI

负责 Agent-local context/cognition/Decision contracts 与 Cognitive Executor SPI。

`Decision::Act` 使用 Protocol 的 `ActionInvocation`，因此 Agency 不需要依赖 Runtime。

v0 cognition 标准路径留在 Agency，不把 generic CognitiveExecutor handle 塞进普通 Capability Resolver host context。

### 3.6 `loom-runtime` — Execution Authority

负责：

```text
ExecutionSession / ExecutionAssembly
World Runtime Binding enforcement
Runtime-backed World Views
ReadSet
ResolutionBudget
Effect Engine
Candidate overlay
ValidatedResolution authority gate
controlled entropy
World-Time logical authority
Durable Work logical chronology
semantic due-ness / operational claimability separation
head-of-line / quiescence enforcement
Durable Work execution / logical transitions
Timeline logical CAS/commit orchestration
Runtime Revision execution state
Runtime-required persistence ports
implementation of loom-api services
```

Runtime 可以持有 installed Capability registry，但所有 target-World dispatch 必须再经过 World Runtime Binding。

### 3.7 `loom-storage` — Persistence Adapter

负责 PostgreSQL/pgvector/object-store 的具体实现，并实现 Runtime-owned persistence ports。

Runtime 不依赖 Storage concrete crate；Application composition root 将 `PgStorage` 注入 Runtime。

Storage 不因为持久化 World Binding、Logical Commit、Work order 或 Provenance 就获得解释这些语义的 authority。

### 3.8 `loom-boundary` — Transport Adapter

负责 HTTP/JSON、SSE、必要时 WebSocket 等 transport concern，并**只把 transport 映射到 `loom-api`**。

Boundary 不直接调用 Runtime internal type，也不直接调用 Capability Resolver，更不能直接更新 World Time/Binding/Work ordering 数据库字段。

---

## 4. Mandatory Cargo Dependency Direction

本节约定：

> **`A -> B` 表示 A 的 `Cargo.toml` 依赖 B。**

允许的 Framework 依赖：

```text
loom-protocol
-> loom-core

loom-api
-> loom-core
-> loom-protocol

loom-capability
-> loom-core
-> loom-protocol

loom-agency
-> loom-core
-> loom-protocol

loom-runtime
-> loom-core
-> loom-protocol
-> loom-api
-> loom-capability
-> loom-agency

loom-storage
-> loom-core
-> loom-runtime

loom-boundary
-> loom-api
```

禁止形成：

```text
runtime <-> capability
runtime <-> agency
runtime <-> storage
runtime <-> boundary
```

World Runtime Binding / World Time / scheduler chronology closure 不改变这张 DAG。

### 4.1 Port ownership

Port 放在需要能力的一侧。

```text
Capability needs host query/subresolution/entropy
-> port belongs to loom-capability
-> Runtime implements it

Runtime needs persistence / World Binding read / logical commit / time transition / deterministic Work claim storage
-> ports belong to loom-runtime
-> loom-storage implements them

Application/transport needs Loom capability
-> contract belongs to loom-api
-> Runtime implements it
-> loom-boundary adapts transport to it

Runtime needs cognition
-> SPI belongs to loom-agency
-> concrete provider adapter implements it
```

这使运行时调用方向可以与 Cargo dependency 方向不同，同时保持无环。

### 4.2 Composition root

`loom-server` 是主要 composition root，负责实例化并连接：

```text
Runtime
PgStorage
installed Capability registry / concrete capabilities
Runtime Revision metadata
Cognitive providers
Platform Clock / Entropy implementation
World-time policy/controller
HTTP Boundary
```

Runtime 本身不负责 import/construct 具体 Storage、HTTP server、领域 Capability 或 provider implementation。

Composition root 安装 Capability implementation；它不决定某个 World 自动 enabled 哪些 Capability。World Runtime Binding 是持久 World metadata，由 Runtime 执行时强制。

Composition root 也不决定某条 Timeline 的 next Work；scheduler chronology 属于 Runtime + persisted logical state contract。

### 4.3 Machine enforcement

`tools/check_architecture.py` 通过 `cargo metadata` 检查 workspace 直接依赖边及关键基础设施泄漏；CI 在 `cargo check` 前执行它。

新增不在 allowlist 内的 edge 必须先经过架构评审并更新 `governance.md`，不能为了让 CI 变绿直接修改 checker。

完整强制规则见 `docs/architecture/governance.md`。

---

## 5. One Public Loom API

> **Extension defines semantics; Loom owns exposure.**
>
> **One engine, one public contract, many semantic extensions.**

Capability 可以定义：

```text
finance.transfer
employment.contract
social.publish
```

但 Capability 不能定义：

```text
POST /finance/transfer
FinanceController
finance-specific public CLI command as an engine bypass
GPUI engine endpoint
public WebSocket/gRPC service
SDK service that bypasses Loom API
```

统一路径：

```text
HTTP / GPUI / CLI / SDK
          ↓
        Loom API
          ↓
        Runtime
          ↓
load target World Runtime Binding
          ↓
resolve semantic owner in pinned Execution Assembly
          ↓
 owning Capability Resolver
```

### 5.1 Loom API capability domains

v0 对外 contract 按 Loom 自身能力组织，而不是按领域模块组织：

```text
World API
Timeline API
Action API
Query API
History API
Subscription API
Catalog / Discovery API
Admin / Runtime Control API
```

统一入口不意味着一个巨大 God Trait；实现时应按职责拆成小 service traits。

### 5.2 World API vs Admin / Runtime Control API

二者都属于 Loom public contract，但必须分离 namespace/authorization boundary：

```text
World API
= observe / interact with World and Timeline semantic surfaces

Admin / Runtime Control API
= operate Runtime/platform lifecycle and authorized Timeline controls
```

World Time advancement 是 Timeline runtime control，不是领域 Action。它可以被 Application policy/Operator 触发，但最终必须进入 Runtime-owned explicit time-transition authority，并先满足 due-work quiescence barrier。

Runtime admin 操作不能伪装成领域 Action；Capability 也不能借 Action 获取平台管理权限。

当前 v0 实现将该边界落实为 `loom_api::AdminService` 与独立的
`/v1/admin` Boundary router。Boundary 通过独立的 `AdminAuthorizationHook`
在调用 Admin service 前完成授权；Runtime 只把 Revision、Session/安全
provenance、Timeline logical status 和 liveness 条件投影为稳定 Loom 值。
Work terminalization 与 World-Time advancement 仍分别进入
`RuntimeControlStore`/`WorldTimeStore` 的 CAS + Logical Journal authority
路径，不能由 Boundary 或 Client 直接写存储。

### 5.3 Capability Discovery

必须区分两种 Catalog：

```text
Global Installed Catalog
= 当前软件环境有哪些 semantics/implementations

World-Scoped Catalog
= 某个 World Runtime Binding 启用了哪些 semantics，并且当前 Runtime 有 compatible implementation
```

Loom 统一暴露 Catalog descriptor，使 Consumer 可以发现：

```text
installed Capabilities where globally requested
World-enabled Capabilities where target-scoped
semantic IDs
Actions
Facets
Relationships
Events
schemas / schema revisions
dependencies / ownership
```

Studio/CLI 可以根据 schema 动态构造通用交互；定制 UI 仍然通过相同 Loom API 调用语义 Action。

---

## 6. v0 Dependency Baseline

### 6.1 Core

```text
uuid            stable UUID support; v0 IDs use UUIDv7
serde           serialization contracts where required
serde_json      flexible Capability payload/state representation where required
thiserror       typed library errors
```

WorldId、TimelineId、EntityId、RelationshipId、EventId、WorkId、ExecutionSessionId 等使用强类型 wrapper，而不是在公共契约中裸传字符串。

UUIDv7 用于技术身份与良好的索引局部性；Timeline 的权威历史顺序仍由 `event_seq` 定义，不能由 UUID 时间顺序替代。Durable Work 的 logical schedule order 同样不能从 UUIDv7 推导。

### 6.2 Protocol / API

`loom-protocol` 和 `loom-api` 保持纯 contract。允许依赖 Core 和必要的 serialization/schema value libraries，但禁止引入：

```text
SQLx / pgvector / object_store
Axum / concrete HTTP server
provider SDK / reqwest provider implementation
GPUI
Runtime implementation
```

API 不泄漏 `ValidatedResolution`、Storage transaction、ReadSet recorder、Mutation Overlay、raw World Binding persistence row、World-Time commit token、raw Work claim/fence authority 等内部 authority/implementation type。

### 6.3 Runtime

```text
tokio           1.51.x LTS async runtime
rand            controlled entropy implementation
rand_chacha     seeded/reproducible entropy implementation
tracing         structured runtime instrumentation
```

`rand` 不作为 Core/Capability 可随意调用的公共能力。所有会影响 World Truth 的随机性必须通过 Runtime Entropy Boundary。

Runtime 不直接依赖 SQLx/PostgreSQL adapter、Axum transport 或 provider HTTP client。

PlatformClock 只服务 lease/retry/audit；World Time progression 走 Runtime explicit logical transition，不通过 PlatformClock trait 隐式实现。

### 6.4 Capability

```text
schemars        Rust type -> JSON Schema
jsonschema      runtime/schema validation support where contract placement proves appropriate
semver          Capability/API/software compatibility metadata
```

Capability schema 默认采用 JSON Schema 2020-12。

Rust 内建 Capability 可以由强类型结构生成 Schema；Runtime 在 Commit 前至少完成：

```text
World Runtime Binding / owner enablement
candidate state
      ↓
JSON Schema validation
      ↓
Capability invariants
      ↓
Runtime invariants
      ↓
Commit
```

Schema/version metadata 属于软件与 Capability contract，不属于 World Truth。

### 6.5 Storage

```text
sqlx            explicit SQL + PostgreSQL driver + migrations
pgvector        PostgreSQL semantic/vector retrieval
object_store    S3-compatible/object-store implementation substrate
blake3          content integrity/provenance/cache identity
```

不在 v0 引入 ORM。Timeline CAS、Event append、logical commit journal、World Binding persistence、deterministic Work head selection、`FOR UPDATE SKIP LOCKED`、JSONB、递归查询和分区策略都允许使用明确 SQL。

`FOR UPDATE SKIP LOCKED` 只是一种并发实现工具，不能定义“跳过当前 logical head，挑下一条可 claim row”的语义。Runtime persistence port 必须先满足 frozen Work chronology contract。

数据库迁移使用 SQLx migrations，并保留人工可读 SQL。

### 6.6 Boundary / Network

```text
axum            HTTP server adapter
tower           service/middleware contracts
tower-http      HTTP middleware where required
```

外部 provider HTTP adapter 可使用：

```text
reqwest
rustls
url
```

但这些 provider/client dependency 不进入 Core/Protocol/API/Capability/Agency contract 或 Runtime authority crate。

传输协议默认：

```text
Commands / Ingress        HTTP + JSON
Queries                   HTTP + JSON
World Change Feed         SSE
Bidirectional realtime    WebSocket only when genuinely required
```

不因为“实时”默认使用 WebSocket，也不在 v0 默认引入 gRPC。

### 6.7 Application

```text
config           layered application configuration
secrecy          credentials/secrets wrapper
clap             Loom CLI
anyhow           application/binary error aggregation only
```

Library crates 保持 typed error；`anyhow` 不进入 Core/Protocol/API contract。

World-time advancement policy 可以是 Application/Runtime config，但每次实际 advance 必须形成 Runtime logical transition；不能只改进程内 clock variable，也不能绕过 current due-work barrier。

### 6.8 Dev / CI

```text
proptest         property/invariant testing
cargo-deny       advisories/licenses/sources/dependency policy
```

`cargo-nextest`、`testcontainers` 可以在测试规模或本地集成测试需求出现时加入，不作为 Core 设计前提。

---

## 7. Data Foundation

Loom v0 不采用“只有一个存储介质”，而采用：

> **One authoritative database + one blob/object store.**

```text
                         Loom Data
                            │
             ┌──────────────┴──────────────┐
             ↓                             ↓
     PostgreSQL + pgvector            Object Storage
        authoritative DB             large immutable data
```

### PostgreSQL 负责

```text
World identity
World Runtime Binding / Template provenance
Timeline / ancestry / World Time materialization
Timeline logical commit history
Entity / Relationship
Current materialized State / State Facets
Event Ledger
Event participants / causality / relationship refs
Durable Work logical state / effective due time / logical schedule order
Work operational lease/retry metadata
Ingress metadata
Execution / Runtime metadata
Capability software metadata where required
Semantic/vector projections that fit pgvector
```

### Object Storage 负责

```text
raw documents
images / audio / video
large artifacts
large context snapshots
raw model responses
large reports
other immutable or content-addressable blobs
```

PostgreSQL 只保存对象引用、hash、size、content type、provenance 等结构化 metadata。

Object store implementation 通过 Loom 自己的薄 Blob/persistence port 隔离；上层 contract 不绑定某个云供应商。

### 7.1 Authority domains are physically separable

即使都在 PostgreSQL 中，也必须在 schema/transaction semantics 上保持：

```text
World History
Materialized World State
Timeline Logical State
Platform Operational State
Platform Provenance
World Runtime Binding
```

不能因为“一个数据库最方便”就把 lease、Event、World Time、Work order、Runtime Revision、Capability config 混成一套万能 timeline_event。

---

## 8. Authority First, Projections Later

> **Authority first, projections later.**
>
> **先建立唯一权威数据源，再按真实需求增加可重建投影。**

PostgreSQL 是 World/Timeline Runtime Authority；专用 Graph/Search/Analytics/Vector 系统都不是 v0 的 World Truth。

未来可以增加：

```text
PostgreSQL + Object Store
          │
          ├── Graph Projection      -> specialized graph engine
          ├── Search Projection     -> Elasticsearch/OpenSearch
          ├── Analytics Projection  -> ClickHouse or equivalent
          └── Vector Projection     -> specialized vector engine
```

这些系统必须可从 Authority 重建。它们故障或删除不能破坏 World。

pgvector 从 v0 开始启用，因为 semantic retrieval 是 Agency/Memory/Information 很快会使用的基础能力；但 Embedding 是 retrieval projection，不是 Core Truth。

换 embedding model 可以重建 embedding，不得因此重写 Event 或 World State。

---

## 9. World Graph and Event Causal Graph

Loom 一定具有图结构，但“有 Graph”不等于“必须使用 Graph Database”。

### 9.1 World Structural Graph

```text
Entity
  ↕
Relationship
  ↕
Relationship Participant
```

Relationship 是有自身 ID、State、Lifecycle 的 Core structural primitive，并允许 N-ary participants。PostgreSQL 使用关系表保存权威结构。

### 9.2 Event Graph

Event 中凡是需要关联、索引、因果追踪和完整性约束的结构必须关系化，不能只塞入 JSONB。

```text
world_event
    │
    ├── event_participant
    │      └── event ↔ entity + role
    │
    ├── event_relationship
    │      └── event ↔ relationship + role
    │
    ├── event_causality
    │      └── cause_event ↔ effect_event + relation kind
    │
    └── event_scope
           └── target / population reference where required
```

因此以下查询必须是正常索引/图遍历问题，而不是 JSON 文本扫描：

- 一个 Event 直接涉及哪些 Entity；
- Entity 在 Event 中是什么 role；
- Event 操作或引用了哪些 Relationship；
- 哪些 Event 导致当前 Event；
- 当前 Event 派生了哪些后续 Event；
- 一条多层 causal chain 中出现了哪些 Entity/Relationship；
- 某次变化直接影响或指向哪些 Population/Scope。

多层 Event causality 初期使用 PostgreSQL recursive CTE；只有出现真实规模/算法瓶颈后才引入专用 Graph Projection。

### 9.3 Direct Participant vs Population

不能把大型事件涉及的几百万个受众全部展开成 `event_participant`。

- `event_participant`：直接参与、发起、决策、操作或明确进入事件事实结构的主体；
- `event_scope`：群体、受众、市场、人群、组织范围等可计算或语义化目标。

Population 的领域语义由 Capability 定义，Core 只提供可引用的 scope/target mechanism。

### 9.4 Event graph is not logical/provenance graph

以下都不能进入 `event_causality` 伪装成 World facts：

```text
World Time advancement
Work claim/retry
Work logical schedule ordering
Resolution subcall
Execution Session -> Runtime Revision
Capability implementation selection
```

---

## 10. Event, State, World Time and Durable Work Persistence

权威模型修正为：

```text
Event Ledger           = determined semantic past
Materialized State     = current semantic world
World Time             = current Timeline semantic time coordinate
Durable Work           = unresolved logical future execution
Logical Work Order     = deterministic same-Timeline future chronology
Logical Commit Journal = reconstructable Timeline time/future transitions
```

Event Ledger append-only。Current semantic State 是 Event Ledger/frozen Effects 的 materialized projection，不创建另一套独立 semantic history 权威。

World Time、logical Work 和 Work order 由 Timeline Logical Commit Journal/authoritative logical state 重建；不能通过 Event timestamp、当前 Work table 偶然顺序或 UUID 猜历史。

Event envelope 的稳定关联字段关系化；领域 payload 与冻结的 resolved effects 可以使用 JSONB/typed serialization。

> **Queryable structure must be normalized; flexible semantics may remain JSONB.**

即：凡是 Core 明确需要关联、索引、追踪和完整性约束的结构优先关系化；领域可变语义保留给 Capability payload/facet JSONB。

---

## 11. Timeline Logical Commit Transaction

Timeline Logical Commit 是所有 reconstructable Timeline mutation 的唯一线性化边界。

Resolve/Cognition 可以并行、缓慢并发生在事务外；Commit 必须保持短事务。

### 11.1 Semantic commit

```text
Read snapshot + expected TimelineVersion
        ↓
start/pin Execution Session Assembly
        ↓
Resolve / Cognition / Evaluate
        ↓
Runtime Validation
        ↓
ValidatedResolution
        ↓
BEGIN
        ↓
Validate TimelineVersion / CAS
Validate World Runtime Binding / current Work claim as required
Validate scheduler logical-head condition for Work execution
        ↓
Append 0..N committed Events
        ↓
Apply frozen Effects to materialized State
        ↓
Create/cancel Durable Work
Allocate/persist effective due time + logical schedule order
Complete current Work when applicable
        ↓
Append logical commit / Work transitions
        ↓
Advance Timeline logical revision/head
Persist required provenance links
        ↓
COMMIT
```

### 11.2 World-Time-only commit

World Time advancement 不走 Capability Resolution，也不伪造 Event：

```text
AdvanceWorldTime(expected_version, from, to)
        ↓
BEGIN
        ↓
Validate TimelineVersion / current World Time
Validate no semantically due Pending Work
Validate monotonic target
        ↓
Append logical time transition
Update materialized timeline.world_time
Advance logical revision
        ↓
COMMIT
```

Pure time advancement 不增加 EventSeq。

### 11.3 Allowed commit forms

```text
Event-only
Event + Work
Work-only logical commit
World-Time-only logical commit
true NoChange -> no logical commit
```

一个 pure Work completion/schedule/cancel 可以推进 TimelineVersion 而不增加 EventSeq。

### 11.4 Atomicity failures forbidden

不得出现：

```text
Event committed but State missing
State changed but Event missing
Event/State committed but required future Work lost
Work-generated Event committed while current Work stays Pending
Work scheduled without persistent deterministic logical order
World Time field changed without logical history
World Time advanced while semantically due Pending Work exists
logical commit journal written while authority mutation rolled back
Event committed without required producing Session linkage once provenance contract requires it
```

### 11.5 Concurrency

不在长时间 Resolve/LLM 计算期间锁 Timeline。

默认采用：

```text
optimistic concurrency
+
TimelineVersion CAS
+
short commit transaction
```

冲突意味着当前 Resolution / time transition 基于旧 World snapshot，不得直接落库；Runtime 必须重新读取并根据策略 revalidate / resolve / re-plan transition。

Scheduler-managed Work admission 在同一 Timeline 必须遵守 persistent logical head；不能因为多 worker 并发而让 later Work 先获得语义执行资格。

---

## 12. World Time, Work Chronology and Platform Time

World Time 与平台时间严格分离。

```text
WorldInstant / WorldDuration
    Timeline semantic time

Platform timestamp
    committed_at / received_at / retries / leases / runtime audit
```

Core World Time 使用可排序的整数语义类型，不直接暴露 `TIMESTAMPTZ`/系统时钟。

### 12.1 World Time is explicit logical state

禁止：

```text
world_time = max(event.occurred_at)
world_time = database NOW()
world_time += worker sleep duration
world_time = retry available_at
```

World Time 只能由 Runtime explicit `AdvanceWorldTime` authority transition 持久推进。

### 12.2 Event time

v0 Event 的 `occurred_at` 必须等于 Resolver 读取的 pinned Timeline World Time。

若领域需要：

```text
source timestamp
legal effective date
historical observation time
external report time
```

使用明确 domain payload/scope/metadata，不用 Event timestamp 偷偷推进 clock。

### 12.3 Work dual clocks are not equivalent

Durable Work 至少区分：

```text
effective due World Time
= when the Timeline considers the Work due

available_at Platform Time
= when the platform may technically retry/claim it
```

Semantic due-ness：

```text
status = Pending
AND
effective_due_world_time <= current Timeline.world_time
```

Operational claimability 还需要：

```text
available_at <= PlatformTime.now
no valid lease
compatible handler implementation available
```

所以 `available_at` 不能参与“这个 Work 是否已经在世界语义上到期”的判断。

现实服务器 retry 30 秒不能自动让 World Time 前进 30 秒，也不能让 later Work 越过当前 due head。

### 12.4 Persistent same-Timeline Work order

Scheduler-managed Work 的 v0 逻辑排序为：

```text
(effective_due_world_time, logical_schedule_order)
```

其中 `logical_schedule_order` 是持久 Timeline-local order，由 Logical Commit 分配。

明确禁止使用：

```text
UUID / UUIDv7
DB natural row order
worker race
lease acquisition speed
wall-clock race
```

作为逻辑排序。

Immediate Work 的 effective due time = schedule commit 的 current World Time；同一 commit 的多个 Work 按 validated WorkMutation stable order 分配 sequence。

### 12.5 Head-of-line / quiescence rule

只要 Timeline 的 logical head 已经 semantically due：

- later Work 不能先 claim/execute；
- retry backoff 不能让 later Work skip；
- active lease 不能让 later Work skip；
- temporarily missing implementation 不能让 later Work skip；
- World Time 不能前进。

head 必须通过 Logical Commit 进入 `Completed / Cancelled / Dead` 后，barrier 才解除。

### 12.6 Time policy vs authority

Runtime/Application 可以配置：

```text
manual/external advancement
next-due jump
paced simulation
real-world mirror mapping
custom policy
```

但 policy 只决定“是否请求推进到哪里”；真正 Timeline mutation 必须通过 `AdvanceWorldTime` logical commit。

自动 next-due policy：

- 只有在没有 semantically due Pending Work 时才允许推进；
- 跳到最小 future effective due World Time；
- advance commit 与后续 Work execution 分离，保证 crash/restart 可恢复；
- restart 后按 persistent logical head 恢复，不重新依赖 DB 偶然顺序。

---

## 13. Durable Work

Durable Work 与生成它的 Event/State change 必须能够在同一 PostgreSQL transaction 中落库。

v0 调度/claim 可以使用 PostgreSQL transaction + `FOR UPDATE SKIP LOCKED`，但该 SQL 技术必须服从 Runtime logical-head contract；不引入 Redis queue 作为 future authority。

Runtime 可以 at-least-once 执行 Work，但 World Commit 必须支持 fencing/CAS/idempotency，防止重复 World mutation。

Work 的核心语义与状态机以 `runtime-contracts.md` 为准：

```text
Pending / Completed / Cancelled / Dead
claim = lease, not state
World reschedule = new Work
technical retry = same Work + platform backoff
semantic due-ness != operational claimability
same-Timeline order = effective due + logical schedule order
```

### 13.1 Logical Work vs operational Work metadata

必须物理/语义上可区分：

```text
Logical Future State
= Work identity / handler / payload / effective due World Time
  / logical schedule order / status / causal origin

Operational State
= lease / fence / retry available_at / attempt count / last_error
```

只有前者进入 Timeline logical history / fork reconstruction。

### 13.2 World Binding enforcement

Work 创建时 handler 必须属于 target World enabled semantic assembly；真正执行时还必须重新确认：

```text
World Binding still identifies the semantic owner (v0 immutable)
current active Runtime Revision has a compatible exact handler implementation
```

Work 不永久 pin 创建时的 implementation binary。

如果 logical head 当前缺少 compatible handler，Scheduler progression 被阻塞；不能选择 later Work 作为替代。

### 13.3 Deterministic claim semantics

Persistence adapter 的“claim next”必须实现 Runtime 语义，而不是定义 Runtime 语义。

概念上先决定：

```text
logical head among Pending Work
        ↓
is head semantically due?
        ↓
is that same head operationally claimable?
```

只有答案最终为 yes 才 claim。

不能执行：

```sql
SELECT any_available_row
ORDER BY available_at
FOR UPDATE SKIP LOCKED
LIMIT 1
```

并把结果当作世界 chronology；实际 SQL 结构可以不同，但行为必须等价于 frozen contract。

---

## 14. Fork Persistence

v0 优先简单、正确的实现：

```text
Fork Timeline
├── references parent ancestry
├── begins at explicit TimelineVersion fork position
├── reconstructs/copies materialized State at fork point
├── copies fork-point World Time
├── clones pending logical Durable Work as branch-local future
├── preserves inherited effective due time + relative logical schedule order
└── resets lease/fence/retry operational metadata
```

共享的是：

```text
World identity
World Runtime Binding
history ancestry up to fork point
```

不共享的是：

```text
post-fork materialized State
post-fork World Time
post-fork Work lifecycle
operational leases/retries
future outcome
```

child Timeline 后续新 Work 的 logical order 从 inherited high-water mark 之后继续分配。

不在 v0 提前实现复杂 copy-on-write branch storage。真实规模证明必要后再优化。

---

## 15. Controlled Nondeterminism

所有会影响 World Truth 的非确定性必须有明确边界：

```text
external input   -> Loom Boundary/API Ingress
cognition        -> Agency Cognitive Executor
randomness       -> Runtime Entropy Service
time             -> explicit World-Time logical authority
```

Capability 不得隐藏调用：

```text
system random
system/platform clock as world time
network
model/provider
external API
```

Replay 使用 committed Event 中已经冻结的结果 + Timeline logical history，不重新抽随机数或重新调用模型。

Scheduler worker race **不是**允许的 World-affecting nondeterminism；same-Timeline Durable Work ordering已经由 persistent logical order 冻结。

### 15.1 Capability host entropy

Resolver 若需要 randomness，只能请求 host-controlled entropy sample；Runtime 记录 execution provenance/budget evidence。

### 15.2 Cognition stays in Agency by default

标准 v0：

```text
AgentWorldView
      ↓
Cognitive Executor
      ↓
Decision
      ↓
ActionInvocation
      ↓
normal Runtime / Capability authority
```

普通 `ResolutionContext` 不提供 generic CognitiveExecutor/network/provider handle。

---

## 16. Cognitive / Semantic Retrieval Boundary

Core 不依赖 LLM vendor SDK，也不把 Agent 定义成 LLM。

```text
AgentWorldView
      ↓
Cognitive Executor
      ↓
Decision
      ↓
ActionInvocation (loom-protocol)
      ↓
Runtime / World Binding / Capability Resolver
      ↓
Resolution
      ↓
Validation / Logical Commit
```

具体 Provider adapter 使用普通 HTTP (`reqwest` + `rustls` + Serde) 即可，但它实现 `loom-agency` SPI，不进入 Runtime/Core contract。

Semantic retrieval 可以由 Agency/Capability contract 表达，由 Storage 的 pgvector implementation 提供，经 Runtime-controlled view/port 使用。

Semantic index owner 必须对目标 World enabled；global index registration 不是 World authorization。

Core/Protocol/API 不出现 provider/model/API-key/embedding-model implementation 语义。

---

## 17. Runtime Revision and Execution Provenance

World Runtime Binding 与 exact software version 必须分离。

```text
World Runtime Binding
Capability A requirement ^1

Execution Session S100
Runtime Revision R18
Capability A implementation 1.7.3
```

新的 R19 若提供 A 1.8.0 且 compatible，新 Session 可以使用 1.8.0；旧 Event 仍指向 S100/R18/1.7.3 provenance。

Runtime Revision activation：

```text
does not create World Event
does not change materialized State
does not advance World Time
does not mutate World Runtime Binding
```

Execution Session 至少 pin：

```text
World / Timeline
input TimelineVersion
World Runtime Binding hash/revision
Runtime Revision
exact Capability implementations
Execution Policy
ReadSet / call graph
Entropy / cognition evidence when used
origin Work/Ingress/Agent/Application
result Event refs
```

Replay 不依赖旧 implementation 才能恢复 World；Provenance 用于解释，不是 reconstruction authority。

---

## 18. GPUI Direction

Loom 官方 UI 采用 GPUI 作为优先技术方向：

```text
                 Loom API
                    │
               loom-studio
                    │
                  GPUI
             ┌──────┴──────┐
             ↓             ↓
          Native        Web/WASM
```

规则：

1. GPUI 只存在于 `apps/loom-studio` Application 层；
2. Core/Protocol/API contracts/Runtime/Storage/Capability 不依赖 GPUI；
3. Studio 只通过 `loom-api` 消费 Engine capability，不 import Capability/Storage/Runtime internals；
4. 使用经过验证的 Zed commit SHA，不依赖浮动 `main`；
5. GPUI Web backend 仍在快速演进，因此 Native + Web 共用 UI 是目标，不是 Core contract；
6. GPUI API 变化不得要求修改 World/Core contracts。

---

## 19. CI Baseline

GitHub Actions 是统一环境验证入口。

最低验证：

```text
Ubuntu
macOS

python3 tools/check_architecture.py
cargo fmt --check
cargo check --workspace --all-targets --all-features
cargo clippy -- -D warnings
cargo test
```

Architecture Policy 是 CI gate：

- Cargo graph 必须无环；
- workspace direct dependency 必须符合 allowlist；
- Core/Protocol/API/Capability/Agency/Runtime 不得出现已明确禁止的基础设施泄漏；
- 违规是 build failure，不是 warning。

Rust toolchain 必须显式安装/固定，不依赖 GitHub runner 偶然预装的版本。

随着实现推进增加：

```text
PostgreSQL 18 + pgvector integration job
World Binding / time / logical replay parity tests
semantic-due vs operational-claimability tests
same-time deterministic Work-order tests
retry/lease head-of-line blocking tests
fork Work-order preservation tests
GPUI native build where applicable
cargo deny check
property/invariant tests
```

CI 通过只证明当前实现/环境验收通过，不改变 World semantic contracts。

---

## 20. Default-Rejected Dependencies and Shortcuts

以下组件不是永久禁止，但 v0 **默认不引入**。新增必须给出真实需求、不可替代原因和清晰的所有权边界：

```text
Redis
Kafka
NATS
Neo4j / dedicated graph database
Elasticsearch / OpenSearch
ClickHouse
dedicated Vector DB

SeaORM / general ORM
gRPC

vendor-specific LLM SDK in Core/Protocol/API/Runtime contracts
Wasmtime / dynamic plugin ABI

petgraph
chrono alongside the selected platform-time approach
async-trait by default
dashmap / parking_lot / crossbeam by default
```

同样默认拒绝以下“实现捷径”：

```text
Capability-specific public HTTP controller
Capability-specific engine SDK bypass
Runtime importing PgStorage
Boundary importing Runtime internals
Capability/Agency importing Runtime
Application feature code importing Storage repository
moving authority types into shared crate for convenience
using global CapabilityRegistry as per-World enablement
mutating world_time from Event.occurred_at max
using PlatformClock as WorldClock
writing World Time directly in Storage/Application
advancing World Time while semantically due Pending Work exists
treating available_at/lease as semantic due-ness
skipping a due Work because it is retrying/leased/unavailable
ordering same-Timeline Work by UUID/DB row/worker race
bootstrapping semantic State with direct SQL
storing permanent exact Capability implementation pin as World identity metadata
generic network/provider handle in ResolutionContext
```

Graph/Search/Analytics/专用 Vector Engine 若未来加入，只能作为可重建 Projection，除非经过新的 Authority Architecture Review。

---

## 21. Core Mutation, Logical Transition and Commit Outcome

### 21.1 Core value types

Core 首批值类型保持窄而强类型：

```text
WorldId
TimelineId
EntityId
RelationshipId
EventId
WorkId
ExecutionSessionId

WorldInstant
WorldDuration
EventSeq
StateRevision
TimelineVersion
```

ID 的具体生成由 Runtime/allocator 完成；Core 不通过 UUIDv7 生成过程偷偷获得系统时钟或随机源。

`StateRevision` 在 `TimelineVersion` 中表示 Timeline logical state revision；pure World-Time/Work logical commit 也必须推进它。

Work logical ordering 所需 exact Rust type/name 在 implementation planning 决定，但必须保持 Timeline-local、persistent、可比较、可 replay/fork。

### 21.2 Entity and Relationship structure

Entity 是稳定身份，不承载具体领域状态。可变语义通过 Timeline-local State/Facet 表达。

Relationship 拥有稳定 `relationship_id`、类型与 participant structure，并支持 N-ary participants。

v0 原则：

> **Relationship participant structure is immutable after creation.**

若关系主体发生根本变化，应结束旧 Relationship 并创建新 Relationship；关系本身的状态、强度、条款等可通过 State/Facet 演化。这样同一个 Relationship ID 不会在不同历史位置指向完全不同的参与者集合。

### 21.3 Facet boundary

Rust API 可以通过统一的 `FacetOwner` 表达 Entity/Relationship owner，但数据库继续区分 `entity_facet` 与 `relationship_facet`，以保留真实 foreign key 与 referential integrity。

Facet 使用完整 candidate state 做 schema/invariant validation；v0 不把 JSON Patch 作为 Core mutation protocol。

### 21.4 WorldEffect

v0 的 WorldEffect 只表达 Core 能够识别的最小 materialized world structure/state change，例如：

```text
CreateEntity
PutFacet
RemoveFacet
CreateRelationship
EndRelationship
```

`TransferMoney`、`DamageCharacter`、`FireEmployee`、`FallInLove` 等领域动作都不属于 Core Effect；它们由 Capability 解析成 Event + Core WorldEffects。

> **Effect is a world mutation primitive, not a database patch and not a domain action.**

WorldEffect 不能独立 Commit；每一个 WorldEffect 必须隶属于一个 Event。允许 Event 没有 Effect，但不允许 Entity/Relationship/Facet semantic State 在没有 Event 的情况下成为新的 World Truth。

World Time / logical Work transition 不属于 `WorldEffect`。

### 21.5 ProposedEvent and CommittedEvent

Capability/Resolver 通过 `loom-protocol` 产生 `ProposedEvent`；只有 Runtime Commit 成功后才存在 committed Event。

事件的稳定结构包括：

```text
event type / schema revision
occurred_at = pinned World Time
participants
relationship references
causal links
semantic payload
frozen WorldEffects
```

Runtime/Storage 再关联 `timeline_id`、`event_seq`、platform committed timestamp、execution provenance 等提交事实。

Event 不负责推进 Timeline World Time。

### 21.6 Event causality is acyclic

Event causality 必须形成 DAG。

一个 Event 只能引用：

1. 当前 Timeline ancestry 中已经提交的 Event；或
2. 同一 Commit 中逻辑上排在它前面的 Event。

不得形成向后的 causal cycle。Commit 后每个 Event 获得连续 Timeline-local `event_seq`。

### 21.7 Resolution and WorkMutation

Durable Work 属于 Timeline Runtime Future，不属于 materialized World Truth，因此 Work mutation 不进入 `WorldEffect`。

Protocol 的统一 semantic output：

```text
Resolution
├── ProposedEvent[0..N]
└── WorkMutation[0..N]
```

`Resolution` 是未受信任 proposal，不能直接进入 Storage，也不能推进 World Time。

### 21.8 World-Time logical transition

World Time advancement 是 Runtime-owned authority：

```text
AdvanceWorldTime
├── expected TimelineVersion
├── from WorldInstant
└── to WorldInstant
```

它不属于 Capability/Protocol Resolution，也不创建 fake Event。

提交前必须证明当前没有 semantically due Pending Work。

### 21.9 Work completion is part of logical transaction

执行某个 Durable Work 后，当前 Work 的完成与它产生的世界提交必须原子发生：

```text
BEGIN
validate TimelineVersion
validate Work claim/fence/idempotency
validate Work is admitted logical head
validate World Binding / handler compatibility
append Events
apply Effects
create/cancel new Work
allocate deterministic effective due/order for new Work
mark current Work completed logically
append logical transitions
advance Timeline logical revision/head
COMMIT
```

因此崩溃不能造成“Event 已提交但 Work 仍 pending，从而再次产生相同世界变化”。

### 21.10 Zero-event execution outcome

Execution Outcome 允许 `0..N Events`。

合法零 Event logical commit 包括 Work-only logical mutation/completion 和 World-Time-only transition。

真正 `NoChange` 指：

```text
no Event
no Work logical mutation
no World Time transition
no other Timeline logical mutation
```

此时不推进 TimelineVersion。

### 21.11 Effect Engine and candidate overlay

Capability 不能获得 Storage write handle。它只能产生 Protocol `Resolution`。

Runtime Effect Engine 至少负责：

```text
validate World Runtime Binding / semantic enablement
validate event schema / occurred_at World Time
validate causality
validate identities
validate relationship structure
validate semantic ownership
apply Effects to candidate overlay
validate JSON Schema
validate Capability invariants
validate Runtime invariants
validate Work mutations
```

Effect validation 使用 `Base WorldView + Mutation Overlay`，不复制整个 World。后续 Effect/validator 在同一个候选提交中必须看到前面 Effect 已经产生的 candidate state。

最终只有 Runtime-owned `ValidatedResolution` 可以交给 Runtime persistence port 尝试 commit。

`ValidatedResolution` 不进入 `loom-protocol`/`loom-api`，即使 Storage 需要消费它也不能为了方便移动 authority ownership。

---

## 22. Repository and Architecture Rule

当前工作树只保留 Loom 自己的实现与文档。旧 MiroFish 工程代码不设置 `legacy/` 墓地目录；需要追溯时使用 Git 历史或上游仓库。

所有后续开发必须先遵守：

```text
docs/architecture/core.md
docs/architecture/layers.md
docs/architecture/world-runtime.md
docs/architecture/runtime-contracts.md
docs/architecture/evolution.md
docs/architecture/governance.md
docs/principles.md
AGENTS.md
```

Loom v0 architecture baseline 已冻结。依赖 patch/minor、安全升级与不改变边界的实现细节可以按维护流程更新；任何改变冻结 authority/chronology semantics 的工作必须先重新 architecture review。

任何会改变以下内容的实现，必须先回到架构层重新评审并更新规范：

```text
Core authority / World semantics
World Runtime Binding ownership or mutability
World Time authority/progression
semantic due-ness / operational claimability distinction
same-Timeline Durable Work logical ordering
head-of-line / due-work quiescence barrier
Timeline Logical Commit boundary
Protocol/API type ownership
Cargo dependency allowlist
Capability semantic ownership / World enablement
Execution Session / Runtime Revision binding semantics
public Loom API exposure rule
Storage/Boundary dependency inversion
```

禁止“先写违反规范的代码，再让文档迁就实现”。

### 22.1 Re-planning gate

架构冻结之后，下一步不是直接执行旧 roadmap，而是重新规划。

新的 V0 implementation plan / Issues / task records 必须显式覆盖：

```text
World Runtime Binding
World Time logical transition + history
TimelineVersion revised semantics
semantic due-ness vs operational claimability
persistent logical Work order
head-of-line claim semantics
due-work quiescence before time advancement
Replay/Fork of time/work/order
Execution Session provenance seam
```

旧 Issue/Task 如果与本文或 `world-runtime.md` 冲突，以冻结架构为准；旧计划需要被重做，而不是要求架构适配旧实现。

> **Architecture is frozen; re-plan first, implement second.**
