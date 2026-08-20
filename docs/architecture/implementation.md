# Loom v0 Technical Foundation

> Status: confirmed technical baseline after Core v0 conceptual closure.
>
> 本文只负责 Loom v0 的实现技术基线：工程边界、基础依赖、数据权威、持久化、运行环境、UI、Runtime Commit 与 Effect 边界。领域语义仍由 Capability 定义；Core 概念边界以 `core.md` 为准。

## 1. Implementation Principle

> **Implement Loom from the Loom architecture; do not translate MiroFish module-by-module.**

MiroFish 的旧 Python/Vue 实现不再作为 Loom 的工程骨架，也不作为兼容目标。需要参考具体算法、交互或实现思想时，可以查看 Git 历史或上游源码；Loom 不为旧接口、旧流程或旧数据模型保留兼容层。

Loom v0 采用 Rust 独立实现。

## 2. Version Policy

Loom 不机械追逐所有依赖的 `latest`，也不长期停留在过时版本。

默认规则：

1. 有官方 LTS 的基础组件：采用最新仍受支持的 LTS；
2. 没有 LTS 的组件：采用最新稳定版本；
3. Rust toolchain、关键框架与快速演进依赖必须可复现地锁定；
4. 应用仓库提交 `Cargo.lock`；
5. 依赖升级属于 Runtime / Platform Change，不属于 World History；
6. 升级不得静默改变已提交 World Event 的历史语义。

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

## 3. Workspace Ownership

```text
crates/loom-core
    World primitives, identity, timeline/state/history contracts and hard invariants

crates/loom-runtime
    execution sessions, durable work, world time, scheduling, entropy,
    resolution, Effect validation and the unique commit authority

crates/loom-capability
    capability registration/binding/invocation, schema and semantic extension contracts

crates/loom-agency
    agent-local view/context, semantic retrieval, decision contracts
    and cognitive executor boundary

crates/loom-boundary
    external ingress, HTTP/API boundary and committed-world feedback/output boundary

crates/loom-storage
    PostgreSQL/pgvector/object-storage implementations hidden behind runtime contracts

apps/loom-server
    server process and runtime composition

apps/loom-cli
    operator/developer CLI

apps/loom-studio
    official GPUI application; Native + Web/WASM target
```

这些 crate 是代码责任边界，不是微服务边界。v0 保持单体 Rust workspace，不为了未来规模提前拆服务。

## 4. Dependency Direction

```text
                    Applications
             ┌──────────┼──────────┐
             ↓          ↓          ↓
           Server      CLI       Studio
             ↓                     ↓
          Boundary                 GPUI
             ↓
           Runtime
       ┌─────┼──────────┐
       ↓     ↓          ↓
    Agency Capability Storage
       \      |         /
             Core
```

关键规则：

- `loom-core` 不依赖 Tokio、SQLx、Axum、GPUI、pgvector、HTTP client、LLM SDK 或随机数实现；
- Core 中的 World Time 使用 Loom 自己的语义类型，不直接暴露平台日期时间类型；
- Capability 不直接持有数据库、网络、系统时钟、随机数源或 Commit Authority；
- Storage 负责实现持久化，不定义 World 语义；
- Application 可以组合实现，但不能反向成为 Core 依赖；
- 根 workspace 可以统一依赖版本，但每个 crate 只声明自己真实使用的依赖。

## 5. v0 Dependency Baseline

### Core

```text
uuid            UUID support; v0 IDs use UUIDv7
serde           serialization contracts
serde_json      flexible Capability payload/state representation
thiserror       typed library errors
```

### Runtime

```text
tokio           1.51.x LTS async runtime
rand            controlled entropy implementation
rand_chacha     seeded/reproducible entropy implementation
tracing         structured runtime instrumentation
```

`rand` 不作为 Core/Capability 可随意调用的公共能力。所有会影响 World Truth 的随机性必须通过 Runtime Entropy Boundary。

### Capability

```text
schemars        Rust type -> JSON Schema
jsonschema      runtime JSON Schema validation
semver          Capability/API/software compatibility metadata
```

Capability schema 默认采用 JSON Schema 2020-12。

### Storage

```text
sqlx            explicit SQL + PostgreSQL driver + migrations
pgvector        PostgreSQL semantic/vector retrieval
object_store    S3-compatible/object-store implementation substrate
blake3          content integrity/provenance/cache identity
```

不在 v0 引入 ORM。数据库迁移使用 SQLx migrations，并保留人工可读 SQL。

### Boundary / Network

```text
axum            HTTP server
Tower           service/middleware contracts
tower-http      HTTP middleware where required
reqwest         external HTTP / cognitive provider adapters
rustls          TLS preference
url             typed URL handling
```

协议默认：

```text
Commands / Ingress        HTTP + JSON
Queries                   HTTP + JSON
World Change Feed         SSE
Bidirectional realtime    WebSocket only when genuinely required
```

### Application

```text
config           layered application configuration
secrecy          credentials/secrets wrapper
clap             Loom CLI
anyhow           application/binary error aggregation only
```

Library crates 保持 typed error；`anyhow` 不进入 Core contract。

### Dev / CI

```text
proptest         property/invariant testing
cargo-deny       advisories/licenses/sources/dependency policy
```

`cargo-nextest`、`testcontainers` 在真实测试规模需要时加入，不作为 Core 设计前提。

## 6. Data Foundation

Loom v0 采用：

> **One authoritative database + one blob/object store.**

```text
                         Loom Data
                            │
             ┌──────────────┴──────────────┐
             ↓                             ↓
     PostgreSQL + pgvector            Object Storage
        authoritative DB             large immutable data
```

PostgreSQL 负责：

```text
World / Timeline
Entity / Relationship
Current State / State Facets
Event Ledger
Event participants / causality / relationship refs
Durable Work
Ingress metadata
Execution / Runtime metadata
Capability metadata
Semantic/vector projections that fit pgvector
```

Object Storage 负责：

```text
raw documents
images / audio / video
large artifacts
large context snapshots
raw model responses
large reports
other immutable or content-addressable blobs
```

PostgreSQL 只保存对象引用、hash、size、content type、provenance 等结构化 metadata。Object store implementation 通过 Loom 自己的薄 `BlobStore` contract 隔离；上层不得绑定某个云供应商。

## 7. Authority First, Projections Later

> **Authority first, projections later.**
>
> **先建立唯一权威数据源，再按真实需求增加可重建投影。**

PostgreSQL 是 World Authority；专用 Graph/Search/Analytics/Vector 系统都不是 v0 的 World Truth。

```text
PostgreSQL + Object Store
          │
          ├── Graph Projection
          ├── Search Projection
          ├── Analytics Projection
          └── Vector Projection
```

这些系统必须可从 Authority 重建。pgvector 从 v0 开始启用，因为 semantic retrieval 是 Agency/Memory/Information 很快会使用的基础能力；Embedding 是 retrieval projection，不是 Core Truth。换 embedding model 可以重建 embedding，不得因此重写 Event 或 World State。

## 8. World Graph and Event Causal Graph

Loom 一定具有图结构，但“有 Graph”不等于“必须使用 Graph Database”。

### World Structural Graph

```text
Entity
  ↕
Relationship
  ↕
Relationship Participant
```

Relationship 是有自身 ID、State、Lifecycle 的 Core structural primitive，并允许 N-ary participants。PostgreSQL 使用关系表保存权威结构。

### Event Graph

凡是需要关联、索引、因果追踪和完整性约束的 Event 结构必须关系化，不能只塞入 JSONB。

```text
world_event
    ├── event_participant       event ↔ entity + role
    ├── event_relationship      event ↔ relationship + role
    ├── event_causality         cause event ↔ effect event + relation kind
    └── event_scope             target / population reference when required
```

因此“某事件涉及谁、某人参与哪些事件、哪些事件导致它、它派生了哪些事件、多层因果链经过哪些 Entity/Relationship”等查询必须是正常索引/递归图遍历问题，而不是 JSON 文本扫描。

大型受众不展开成数百万 `event_participant`：直接参与者进入 participant；群体、受众、市场、组织范围进入 scope。Population 领域语义由 Capability 定义。

> **Queryable structure must be normalized; flexible semantics may remain JSONB.**

## 9. First Core Value Types

第一批 Core 类型保持强语义、低依赖：

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
```

ID 使用 newtype，不在 Core API 中裸传 `Uuid`/`String`。UUIDv7 用于技术身份与索引局部性；权威历史顺序只由 Timeline-local `event_seq` 定义。

UUIDv7 的生成不由 `loom-core` 自行调用系统时钟/随机数完成，而由 Runtime/allocator 边界提供。

Timeline 读取版本至少包含：

```text
TimelineVersion
├── head_event_seq
└── state_revision
```

Resolve 基于某个 TimelineVersion，Commit 时版本已变化则不得直接落库。

## 10. Identity and Timeline Existence

Entity identity 属于 World；mutable State 属于 Timeline。

Entity Core identity 保持很小，不承载 age/money/health/emotion 等领域字段。

同一 World 内 Entity ID 全局唯一，但某个 Entity 是否存在于某条 Timeline，取决于该 Timeline 的 identity/state history。Fork 后在分支 A 新创建的 Entity 不自动出现在分支 B。

## 11. Relationship Structure

Relationship participants 在创建后视为结构身份的一部分，v0 不直接修改 participant set。

如果关系主体发生根本变化：

```text
E1 works_for E2
↓
E1 works_for E3
```

应结束原 Relationship 并创建新 Relationship，而不是把同一 RelationshipId 的 endpoint 改成另一实体。

Relationship 自身的 status、strength、terms 等可变语义继续通过 State/Facet 演化。Participant role 的含义由 Capability 定义；Core 只维护 Entity 引用、role key、顺序/结构完整性。

Rust API 可以使用统一的 `FacetOwner::{Entity, Relationship}`；数据库仍优先使用 `entity_facet` / `relationship_facet` 等可建立真实 FK 的结构，不为了 API 泛化牺牲 referential integrity。

## 12. WorldEffect v0

`WorldEffect` 只描述 **World Truth mutation primitive**，不是领域动作，也不是数据库 patch。

v0 最小集合：

```text
CreateEntity
PutFacet
RemoveFacet
CreateRelationship
EndRelationship
```

概念形式：

```rust
pub enum WorldEffect {
    CreateEntity { entity_id: EntityId },
    PutFacet {
        owner: FacetOwner,
        facet_type: FacetTypeId,
        schema_revision: FacetSchemaRevision,
        value: serde_json::Value,
    },
    RemoveFacet {
        owner: FacetOwner,
        facet_type: FacetTypeId,
    },
    CreateRelationship {
        relationship_id: RelationshipId,
        relationship_type: RelationshipTypeId,
        participants: Vec<RelationshipParticipant>,
    },
    EndRelationship { relationship_id: RelationshipId },
}
```

Core 不出现 `TransferMoney`、`DamageCharacter`、`FireEmployee`、`PublishNews` 等领域 Effect。它们属于 Capability Event semantics，并由 Resolver 转换成上述最小 WorldEffect。

Facet 默认采用**完整候选状态 replacement**，不把 JSON Patch 作为 Core Effect protocol。Effect 是语义状态操作；底层是否使用 SQL update、JSONB path optimization 等属于 Storage implementation。

如果某 Facet 大到完整候选状态本身成为问题，应先重新检查 Facet 边界；大对象内容进入 Object Storage。

## 13. ProposedEvent and CommittedEvent

Capability / Resolver 只能提出 `ProposedEvent`；只有 Runtime Commit 后才形成 `CommittedEvent`。

ProposedEvent 至少可表达：

```text
event identity/type/schema revision
World-time occurrence/effective information
participants
relationship refs
causal refs
semantic payload
WorldEffect[]
```

CommittedEvent 在此基础上获得 Timeline-local `event_seq`、Timeline identity 与 Runtime provenance 关联。

`committed_at` 属于 Platform Time / Runtime audit，不等价于 World Time。

一个 Event 可以没有 WorldEffect：事实不等于 State Update 包装器。但任何 WorldEffect 都必须归属于一个 committed Event；禁止独立提交 WorldEffect 导致“State 改了但世界历史不知道为什么”。

## 14. Event Causality Invariant

Event causality 在一条 Timeline 的逻辑历史中必须保持 DAG。

一个 Event 只能因果引用：

1. 当前 Timeline ancestry 中已经提交的 Event；或
2. 同一 Commit 中、逻辑顺序位于当前 Event 之前的 Event。

不得产生因果环。一个 Commit 可以提交多个 Event，但内部因果方向只能向前。

## 15. Event, State and Durable Work

权威模型：

```text
Event        = determined past
State        = materialized current world
Durable Work = unresolved future execution
```

Event Ledger append-only。Current State 是 Event Ledger 的 materialized projection，不创建另一套独立历史权威。

Durable Work **不是 WorldEffect**。它属于 Runtime Future State：概念上与 World Truth 分离，但必须能与产生它的 Event/State change 在同一数据库事务中原子落库。

## 16. Execution Outcome

Runtime execution 的合法结果是：

```text
ExecutionOutcome
├── 0..N Events
├── 0..N new/cancelled/superseded Durable Work
└── current Work completion / runtime outcome
```

`0 Events` 是合法结果，例如 NO_ACTION、一次 evaluation 完成但世界没有事实变化。此时不得包含 WorldEffect。

一个 Intent / Work 可以产生 `0..N Events`。当多个 Event 属于同一不可分割 Resolution 时，可在同一 Commit 中原子提交；每个 Event 仍然拥有独立连续 `event_seq`。

## 17. Timeline Commit Transaction

Timeline Commit 是 World Truth 的唯一线性化点。

Resolve/Cognition 可以并行、缓慢并发生在事务外；Commit 必须保持短事务。

```text
Read snapshot + expected TimelineVersion
        ↓
Resolve / Cognition / Evaluate
        ↓
Validate proposal / build candidate overlay
        ↓
BEGIN
        ↓
Validate Timeline revision / CAS
Validate current Work claim/idempotency when applicable
        ↓
Append 0..N committed Events
        ↓
Apply frozen WorldEffects to materialized State
        ↓
Create/cancel/supersede Durable Work
        ↓
Mark current Work completed when applicable
        ↓
Advance Timeline head/revision when World changed
        ↓
COMMIT
```

任何一步失败，整个 transaction 失败。

不得出现：

```text
Event committed but State missing
State changed but Event missing
Event/State committed but required future Work lost
World committed but source Work remains pending and executes again
```

默认并发模型：

```text
optimistic concurrency
+
Timeline revision CAS
+
short commit transaction
```

不在长时间 Resolve/LLM 计算期间持有 Timeline database lock。Commit 冲突意味着当前 Resolution 基于旧世界；Runtime 必须按策略 revalidate / resolve，而不是强行覆盖新 State。

## 18. Effect Engine

Effect Engine 属于 `loom-runtime` 的 World Commit authority，不属于 Capability，也不属于 Storage。

```text
Capability Resolver
        ↓
CommitProposal / ExecutionOutcome
        ↓
Effect Engine
        ├── validate event schema
        ├── validate causality
        ├── validate identity existence/structure
        ├── validate relationship structure
        ├── apply Effects to candidate State Overlay
        ├── JSON Schema validation
        ├── Capability invariants
        ├── Runtime invariants
        └── validate Work mutations
        ↓
Validated Commit
        ↓
Storage transaction
```

Capability 永远拿不到 Storage write handle，也不能直接修改 Ledger/State/Identity。它只能提出语义结果；Runtime 判断是否合法、是否仍基于最新 World、是否可 Commit。

### State Overlay

Effect validation 不复制整个 World。Runtime 使用：

```text
Base WorldView
+
Mutation Overlay
```

同一 Commit 中后续 Effect/validation 读取前面 Effect 已产生的 candidate state；最终 overlay 再由 Storage 在短事务内应用。

## 19. World Time and Platform Time

World Time 与平台时间严格分离：

```text
WorldInstant / WorldDuration
    Core semantic time

Platform timestamp
    committed_at / received_at / retries / runtime audit
```

Durable Work 至少区分：

```text
due_world_time   when the World should consider the work
available_at     when the platform may retry/claim the work
```

现实服务器 retry 30 秒不能自动让 World Time 前进 30 秒。

## 20. Durable Work

v0 调度/claim 优先使用 PostgreSQL transaction + `FOR UPDATE SKIP LOCKED`，不引入 Redis queue 作为 future authority。

Runtime 可以 at-least-once 尝试执行 Work，但“source Work completion + World Commit + successor Work creation”必须在同一事务中闭环，配合幂等/冲突保护避免重复 World mutation。

## 21. Fork Persistence

v0 优先简单、正确：

```text
Fork Timeline
├── references parent ancestry
├── begins head_event_seq at fork position
├── clones current materialized State
└── clones pending Durable Work as branch-local future
```

共享的是历史 ancestry，不是未来结果。不在 v0 提前实现复杂 copy-on-write branch storage。

## 22. Controlled Nondeterminism

所有会影响 World Truth 的非确定性必须有明确边界：

```text
external input   -> Ingress
cognition        -> Cognitive Executor
randomness       -> Runtime Entropy Service
time             -> World Clock
```

Capability 不得隐藏调用 system random、system clock、network、model/provider 或 external API。Replay 使用 committed Event 中已经冻结的结果，不重新抽随机数或重新调用模型。

## 23. Cognitive / Semantic Retrieval Boundary

Core 不依赖 LLM vendor SDK，也不把 Agent 定义成 LLM。

```text
CognitiveRequest
      ↓
CognitiveExecutor
      ↓
DecisionResult / Intent
      ↓
Resolver
      ↓
Commit
```

Provider adapter 初期使用普通 HTTP (`reqwest` + `rustls` + Serde)。Semantic retrieval 可以由 `loom-agency`/Capability contract 表达，由 `loom-storage` 的 pgvector implementation 提供。

Core 不出现 provider/model/API-key/embedding-model 语义。

## 24. GPUI Direction

Loom 官方 UI 优先采用 GPUI：

```text
Loom Engine (Rust)
        ↓
Application Boundary
        ↓
      GPUI
    ↙      ↘
Native   Web/WASM
```

规则：

1. GPUI 只存在于 `apps/loom-studio`；
2. Core/Runtime/Storage/Capability 永远不依赖 GPUI；
3. 使用经过验证的 Zed commit SHA，不依赖浮动 `main`；
4. Native + Web 共用 UI 是 Application 目标，不是 Core contract；
5. GPUI API 变化不得要求修改 World/Core contracts。

## 25. CI Baseline

GitHub Actions 是统一环境验证入口。

最低验证：

```text
Ubuntu
macOS
cargo fmt --check
cargo check --workspace --all-targets --all-features
cargo clippy -- -D warnings
cargo test
```

随着实现推进增加：

```text
PostgreSQL 18 + pgvector integration job
GPUI native build
wasm32-unknown-unknown build
cargo deny check
property/invariant tests
```

Rust toolchain 必须显式安装/固定，不依赖 runner 偶然预装版本。

## 26. Default-Rejected Dependencies

以下组件不是永久禁止，但 v0 默认不引入；新增必须给出真实需求、不可替代原因和清晰所有权边界：

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
vendor-specific LLM SDK in Core/runtime contracts
Wasmtime / dynamic plugin ABI
petgraph
chrono alongside the selected platform-time approach
async-trait by default
dashmap / parking_lot / crossbeam by default
```

Graph/Search/Analytics/专用 Vector Engine 若未来加入，默认只能作为可重建 Projection，除非经过新的 Authority Architecture Review。

## 27. First Implementation Milestone

第一阶段只证明 World Runtime 闭环：

```text
Create World / Timeline
        ↓
create minimal identity/state
        ↓
submit Work / Intent
        ↓
Resolve
        ↓
validate Event + Effects
        ↓
Commit Event + Effects + Work outcome
        ↓
materialize State
        ↓
pause / reload / resume
```

验收至少证明：

```text
commit conflict cannot partially mutate World
replay reproduces materialized State
pending Work survives restart
completed Work cannot duplicate the same World mutation
fork does not cross-contaminate branch State/Future
causal Event relations are queryable and acyclic
semantic/vector retrieval does not become World Truth
Capability cannot bypass Runtime commit authority
```

先不引入完整社会、经济、人类心理或大规模领域 Capability，也不以 LLM 是否接通作为 Core 是否成立的判断标准。

## 28. Next Design Question

下一项必须在实现 Effect Engine 前锁定的技术契约是：

> **Capability Resolution Context 可以看到什么、如何读取、Runtime 如何记录它基于哪些 World State 作出决定。**

需要定义 `WorldView / ReadSet / Resolution Context`，使复杂 Capability 能读取足够的世界结构，同时不能获得数据库全知访问或绕过 Runtime authority。

这项设计还必须回答：读取范围、查询预算、派生/语义查询、并发失效检测、Agent Perceived View 与 authoritative WorldView 的区别。

## 29. Repository Rule

当前工作树只保留 Loom 自己的实现与文档。旧 MiroFish 工程代码不设置 `legacy/` 墓地目录；需要追溯时使用 Git 历史或上游仓库。

技术基线默认冻结，但不像 Core Conceptual Closure 那样要求概念级冻结。依赖 patch/minor、安全升级与实现细节可以按维护流程更新；任何会改变 Core authority、World semantics、Commit boundary 或数据权威的技术变更，必须先回到架构层重新评审。
