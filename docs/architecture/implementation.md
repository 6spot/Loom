# Loom v0 Technical Foundation

> Status: confirmed technical baseline after Core v0 conceptual closure.
>
> 本文只负责 Loom v0 的实现技术基线：工程边界、基础依赖、数据权威、持久化、运行环境、UI 与默认禁止项。领域语义仍由 Capability 定义；Core 概念边界以 `core.md` 为准。

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
    resolution and the unique commit authority

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

目标依赖方向：

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
- Application 可以组合实现，但不能反向成为 Core 依赖。

根 workspace 可以统一依赖版本，但每个 crate 只声明自己真实使用的依赖。

## 5. v0 Dependency Baseline

### 5.1 Core

```text
uuid            stable UUID support; v0 IDs use UUIDv7
serde           serialization contracts
serde_json      flexible Capability payload/state representation
thiserror       typed library errors
```

WorldId、TimelineId、EntityId、RelationshipId、EventId、WorkId、ExecutionSessionId 等使用强类型 wrapper，而不是在 Core 中裸传字符串。

UUIDv7 用于技术身份与良好的索引局部性；Timeline 的权威历史顺序仍由 `event_seq` 定义，不能由 UUID 时间顺序替代。

### 5.2 Runtime

```text
tokio           1.51.x LTS async runtime
rand            controlled entropy implementation
rand_chacha     seeded/reproducible entropy implementation
tracing         structured runtime instrumentation
```

`rand` 不作为 Core/Capability 可随意调用的公共能力。所有会影响 World Truth 的随机性必须通过 Runtime Entropy Boundary。

### 5.3 Capability

```text
schemars        Rust type -> JSON Schema
jsonschema      runtime JSON Schema validation
semver          Capability/API/software compatibility metadata
```

Capability schema 默认采用 JSON Schema 2020-12。

Rust 内建 Capability 可以由强类型结构生成 Schema；Runtime 在 Commit 前至少完成：

```text
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

### 5.4 Storage

```text
sqlx            explicit SQL + PostgreSQL driver + migrations
pgvector        PostgreSQL semantic/vector retrieval
object_store    S3-compatible/object-store implementation substrate
blake3          content integrity/provenance/cache identity
```

不在 v0 引入 ORM。Core persistence、Timeline CAS、Event append、`FOR UPDATE SKIP LOCKED`、JSONB、递归查询和分区策略都允许使用明确 SQL。

数据库迁移使用 SQLx migrations，并保留人工可读 SQL。

### 5.5 Boundary / Network

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

不因为“实时”默认使用 WebSocket，也不在 v0 默认引入 gRPC。

### 5.6 Application

```text
config           layered application configuration
secrecy          credentials/secrets wrapper
clap             Loom CLI
anyhow           application/binary error aggregation only
```

Library crates 保持 typed error；`anyhow` 不进入 Core contract。

### 5.7 Dev / CI

```text
proptest         property/invariant testing
cargo-deny       advisories/licenses/sources/dependency policy
```

`cargo-nextest`、`testcontainers` 可以在测试规模或本地集成测试需求出现时加入，不作为 Core 设计前提。

## 6. Data Foundation

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

Object store implementation 通过 Loom 自己的薄 `BlobStore` contract 隔离；上层不得绑定某个云供应商。

## 7. Authority First, Projections Later

> **Authority first, projections later.**
>
> **先建立唯一权威数据源，再按真实需求增加可重建投影。**

PostgreSQL 是 World Authority；专用 Graph/Search/Analytics/Vector 系统都不是 v0 的 World Truth。

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

## 8. World Graph and Event Causal Graph

Loom 一定具有图结构，但“有 Graph”不等于“必须使用 Graph Database”。

### 8.1 World Structural Graph

```text
Entity
  ↕
Relationship
  ↕
Relationship Participant
```

Relationship 是有自身 ID、State、Lifecycle 的 Core structural primitive，并允许 N-ary participants。PostgreSQL 使用关系表保存权威结构。

### 8.2 Event Graph

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

### 8.3 Direct Participant vs Population

不能把大型事件涉及的几百万个受众全部展开成 `event_participant`。

- `event_participant`：直接参与、发起、决策、操作或明确进入事件事实结构的主体；
- `event_scope`：群体、受众、市场、人群、组织范围等可计算或语义化目标。

Population 的领域语义由 Capability 定义，Core 只提供可引用的 scope/target mechanism。

## 9. Event, State and Durable Work Persistence

权威模型：

```text
Event        = determined past
State        = materialized current world
Durable Work = unresolved future execution
```

Event Ledger append-only。Current State 是 Event Ledger 的 materialized projection，不创建另一套独立历史权威。

Event envelope 的稳定关联字段关系化；领域 payload 与冻结的 resolved effects 可以使用 JSONB/typed serialization。

> **Queryable structure must be normalized; flexible semantics may remain JSONB.**

即：凡是 Core 明确需要关联、索引、追踪和完整性约束的结构优先关系化；领域可变语义保留给 Capability payload/facet JSONB。

## 10. Timeline Commit Transaction

Timeline Commit 是 World Truth 的唯一线性化点。

Resolve/Cognition 可以并行、缓慢并发生在事务外；Commit 必须保持短事务。

```text
Read snapshot + expected revision
        ↓
Resolve / Cognition / Evaluate
        ↓
BEGIN
        ↓
Validate Timeline revision / CAS
        ↓
Append 1..N committed Events
        ↓
Apply frozen Effects to materialized State
        ↓
Create/cancel/supersede Durable Work
        ↓
Advance Timeline head/revision
        ↓
COMMIT
```

任何一步失败，整个 Commit Batch 失败。

不得出现：

```text
Event committed but State missing
State changed but Event missing
Event/State committed but required future Work lost
```

一个 Commit Batch 可以原子提交 `1..N Events`；每个 Event 仍有独立、连续的 Timeline-local `event_seq`。

### Concurrency

不在长时间 Resolve/LLM 计算期间锁 Timeline。

默认采用：

```text
optimistic concurrency
+
Timeline revision CAS
+
short commit transaction
```

冲突意味着当前 Resolution 基于旧 World State，不得直接落库；Runtime 必须重新读取并根据策略 revalidate / resolve。

## 11. World Time and Platform Time

World Time 与平台时间严格分离。

```text
WorldInstant / WorldDuration
    Core semantic time

Platform timestamp
    committed_at / received_at / retries / runtime audit
```

Core World Time 初期使用可排序的整数语义类型，不直接暴露 `TIMESTAMPTZ`/系统时钟。

Durable Work 至少区分：

```text
due_world_time   when the World should consider the work
available_at     when the platform may retry/claim the work
```

现实服务器 retry 30 秒不能自动让 World Time 前进 30 秒。

## 12. Durable Work

Durable Work 与生成它的 Event/State change 必须能够在同一 PostgreSQL transaction 中落库。

v0 调度/claim 优先使用 PostgreSQL transaction + `FOR UPDATE SKIP LOCKED`，不引入 Redis queue 作为 future authority。

Runtime 可以 at-least-once 执行 Work，但 World Commit 必须支持幂等/冲突保护，防止重复 World mutation。

## 13. Fork Persistence

v0 优先简单、正确的实现：

```text
Fork Timeline
├── references parent ancestry
├── begins head_event_seq at fork position
├── clones current materialized State
└── clones pending Durable Work as branch-local future
```

共享的是历史 ancestry，不是未来结果。

不在 v0 提前实现复杂 copy-on-write branch storage。真实规模证明必要后再优化。

## 14. Controlled Nondeterminism

所有会影响 World Truth 的非确定性必须有明确边界：

```text
external input   -> Ingress
cognition        -> Cognitive Executor
randomness       -> Runtime Entropy Service
time             -> World Clock
```

Capability 不得隐藏调用：

```text
system random
system clock
network
model/provider
external API
```

Replay 使用 committed Event 中已经冻结的结果，不重新抽随机数或重新调用模型。

## 15. Cognitive / Semantic Retrieval Boundary

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

Provider adapter 初期使用普通 HTTP (`reqwest` + `rustls` + Serde) 即可。

Semantic retrieval 可以由 `loom-agency`/Capability contract 表达，由 `loom-storage` 的 pgvector implementation 提供。

Core 不出现 provider/model/API-key/embedding-model 语义。

## 16. GPUI Direction

Loom 官方 UI 采用 GPUI 作为优先技术方向：

```text
                   Loom Engine
                       Rust
                        │
               Application Boundary
                        │
                      GPUI
                 ┌──────┴──────┐
                 ↓             ↓
              Native        Web/WASM
```

规则：

1. GPUI 只存在于 `apps/loom-studio` Application 层；
2. Core/Runtime/Storage/Capability 永远不依赖 GPUI；
3. 使用经过验证的 Zed commit SHA，不依赖浮动 `main`；
4. GPUI Web backend 仍在快速演进，因此 Native + Web 共用 UI 是目标，不是 Core contract；
5. GPUI API 变化不得要求修改 World/Core contracts。

## 17. CI Baseline

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

Rust toolchain 必须显式安装/固定，不依赖 GitHub runner 偶然预装的版本。

随着实现推进增加：

```text
PostgreSQL 18 + pgvector integration job
GPUI native build
wasm32-unknown-unknown build
cargo deny check
property/invariant tests
```

CI 通过只证明当前实现/环境验收通过，不改变 World semantic contracts。

## 18. Default-Rejected Dependencies

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

vendor-specific LLM SDK in Core/runtime contracts
Wasmtime / dynamic plugin ABI

petgraph
chrono alongside the selected platform-time approach
async-trait by default
dashmap / parking_lot / crossbeam by default
```

其中 Graph/Search/Analytics/专用 Vector Engine 若未来加入，只能作为可重建 Projection，除非经过新的 Authority Architecture Review。

## 19. First Implementation Milestone

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
Commit Event + Effects
        ↓
materialize State
        ↓
schedule Durable Work
        ↓
pause / reload / resume
```

验收还必须证明：

```text
commit conflict cannot partially mutate World
replay reproduces materialized State
pending Work survives restart
fork does not cross-contaminate branch State/Future
causal Event relations are queryable
semantic/vector retrieval does not become World Truth
```

先不引入完整社会、经济、人类心理或大规模领域 Capability，也不以 LLM 是否接通作为 Core 是否成立的判断标准。

## 20. Core Mutation and Commit Outcome

### 20.1 Core value types

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

### 20.2 Entity and Relationship structure

Entity 是稳定身份，不承载具体领域状态。可变语义通过 Timeline-local State/Facet 表达。

Relationship 拥有稳定 `relationship_id`、类型与 participant structure，并支持 N-ary participants。

v0 原则：

> **Relationship participant structure is immutable after creation.**

若关系主体发生根本变化，应结束旧 Relationship 并创建新 Relationship；关系本身的状态、强度、条款等可通过 State/Facet 演化。这样同一个 Relationship ID 不会在不同历史位置指向完全不同的参与者集合。

### 20.3 Facet boundary

Rust API 可以通过统一的 `FacetOwner` 表达 Entity/Relationship owner，但数据库继续区分 `entity_facet` 与 `relationship_facet`，以保留真实 foreign key 与 referential integrity。

Facet 使用完整 candidate state 做 schema/invariant validation；v0 不把 JSON Patch 作为 Core mutation protocol。

### 20.4 WorldEffect

v0 的 WorldEffect 只表达 Core 能够识别的最小世界结构/状态变化，例如：

```text
CreateEntity
PutFacet
RemoveFacet
CreateRelationship
EndRelationship
```

`TransferMoney`、`DamageCharacter`、`FireEmployee`、`FallInLove` 等领域动作都不属于 Core Effect；它们由 Capability 解析成 Event + Core WorldEffects。

> **Effect is a world mutation primitive, not a database patch and not a domain action.**

WorldEffect 不能独立 Commit；每一个 WorldEffect 必须隶属于一个 Event。允许 Event 没有 Effect，但不允许 State 在没有 Event 的情况下成为新的 World Truth。

### 20.5 ProposedEvent and CommittedEvent

Capability/Resolver 产生 `ProposedEvent`；只有 Runtime Commit 成功后才存在 `CommittedEvent`。

事件的稳定结构包括：

```text
event type / schema revision
world time semantics
participants
relationship references
causal links
semantic payload
frozen WorldEffects
```

Runtime/Storage 再关联 `timeline_id`、`event_seq`、platform committed timestamp、execution provenance 等提交事实。

### 20.6 Event causality is acyclic

Event causality 必须形成 DAG。

一个 Event 只能引用：

1. 当前 Timeline ancestry 中已经提交的 Event；或
2. 同一 Commit 中逻辑上排在它前面的 Event。

不得形成向后的 causal cycle。Commit 后每个 Event 获得连续 Timeline-local `event_seq`。

### 20.7 WorkMutation is not WorldEffect

Durable Work 属于 Runtime Future，不属于 World Truth，因此 Work mutation 不进入 `WorldEffect`。

概念结构：

```text
CommitProposal
├── ProposedEvent[0..N]
└── WorkMutation[0..N]
```

但它们必须能够在同一数据库事务中原子落地。

### 20.8 Work completion is part of the transaction

执行某个 Durable Work 后，当前 Work 的完成与它产生的世界提交必须原子发生：

```text
BEGIN
validate Timeline revision
validate Work claim/idempotency
append Events
apply Effects
create/cancel/supersede new Work
mark current Work completed
advance Timeline head/revision
COMMIT
```

因此崩溃不能造成“Event 已提交但 Work 仍 pending，从而再次产生相同世界变化”。

### 20.9 Zero-event execution outcome

Execution Outcome 允许 `0..N Events`。

`0 Events` 只允许 NO_ACTION、纯 evaluation 完成或其他不改变 World Truth 的 Runtime outcome；此时仍可完成当前 Work。任何 WorldEffect 都要求至少一个 Event。

### 20.10 Effect Engine and candidate overlay

Capability 不能获得 Storage write handle。它只能产生 Commit Proposal。

Runtime Effect Engine 至少负责：

```text
validate event schema
validate causality
validate identities
validate relationship structure
apply Effects to candidate overlay
validate JSON Schema
validate Capability invariants
validate Runtime invariants
validate Work mutations
```

Effect validation 使用 `Base WorldView + Mutation Overlay`，不复制整个 World。后续 Effect/validator 在同一个候选提交中必须看到前面 Effect 已经产生的 candidate state。

最终只有 `ValidatedCommit` 可以进入 Storage 的 PostgreSQL transaction。

## 21. Repository Rule

当前工作树只保留 Loom 自己的实现与文档。旧 MiroFish 工程代码不设置 `legacy/` 墓地目录；需要追溯时使用 Git 历史或上游仓库。

技术基线默认冻结，但它不像 Core Conceptual Closure 那样要求概念级冻结。依赖 patch/minor、安全升级与实现细节可以按维护流程更新；任何会改变 Core authority、World semantics、Commit boundary 或数据权威的技术变更，必须先回到架构层重新评审。
