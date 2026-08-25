# Loom v0 Runtime Contracts

> Status: **FROZEN — normative Loom v0 Runtime contract.**
>
> 本文详细定义 Loom v0 从“请求一个世界行为”到“世界事实或 Timeline logical state 被提交”的运行契约。`core.md` 定义概念边界，`world-runtime.md` 定义 World Runtime Binding / World Time / Execution Session / scheduler chronology 的交叉闭环，`implementation.md` 定义技术基线，`governance.md` 强制约束 Rust crate 依赖与统一对外暴露；本文负责把这些原则落实为可编码、可测试、可审计的 Runtime/Capability 协议。
>
> 本文优先解释**概念语义和所有权**。Rust 代码片段是接口草图，不代表最终语法必须一字不差。若实现细节需要调整，不能静默改变本文已经锁定的 authority、truth、ownership、dependency、binding、time、scheduler chronology 或 transaction boundary。

## 0. Documentation Contract

Loom 的核心抽象不能只靠名字表达语义。每一个公开的 Core/Protocol/API/Runtime/Capability/Agency 类型、trait、关键 enum variant 与高风险字段，在代码中都必须使用 Rust doc comments (`///` / `//!`) 说明至少以下内容：

1. **Meaning**：它在 Loom 世界模型或执行模型中代表什么；
2. **Owner**：哪个 crate / Runtime component 拥有它的解释权；
3. **Truth domain**：它属于 World History、Materialized World State、Timeline Logical State、Platform Operational State、Execution Provenance、Agent Knowledge、public API contract 还是 software metadata；
4. **Input / output boundary**：谁可以创建、读取、修改或消费它；
5. **Forbidden use**：它明确不能被用来做什么；
6. **Relationship**：它与最容易混淆的相邻概念有什么区别；
7. **Persistence**：若持久化，权威位置和生命周期是什么；
8. **Concurrency / version rule**：若涉及 Snapshot、Revision、Commit 或 Retry，必须写清楚一致性规则；
9. **Exposure rule**：若进入 `loom-api` 或 transport，必须说明它是否属于稳定 public contract，禁止把 Runtime internal type 意外泄漏出去。

禁止只写这类无信息注释：

```rust
/// Represents a resolution.
struct Resolution { /* ... */ }
```

应写成能够独立帮助维护者恢复设计意图的注释：

```rust
/// Untrusted semantic output produced by a Capability resolver.
///
/// A `Resolution` describes the Events, World Effects and future Work that a
/// resolver believes should follow from one invocation. It is **not** World
/// Truth and cannot be committed directly. Runtime validation must transform
/// it into a Runtime-owned `ValidatedResolution` before persistence may commit
/// it.
///
/// Unlike `Decision`, this value already contains resolved world semantics.
/// Unlike `ValidatedResolution`, it has not crossed the Runtime authority gate.
pub struct Resolution { /* ... */ }
```

> **Documentation is part of the contract.** Missing semantic documentation on a new public Core/Protocol/API/Runtime abstraction is an implementation defect, not optional cleanup.

---

## 1. Runtime Contract Map

Loom v0 的 root semantic execution 必须先建立一套 pinned Execution Assembly，再进入唯一的 Resolution authority path：

```text
Stimulus / Application / Ingress / Durable Work
                    │
             optional Agency
                    │
                 Decision
                    │
            ActionInvocation
                    │
       Runtime starts Execution Session
                    │
          load complete persisted World Runtime Binding
                    │
       require confirmed active Runtime Revision
                    │
 exact compatibility check against complete Binding
          ├─ missing/incompatible → typed unavailable/error
          └─ compatible → resolve exact compatible implementations
                    │
           Runtime Router
                    │
           Capability Resolver
                    │
                Resolution
                    │
             Effect Engine
                    │
          CandidateWorldView
                    │
        Schema + Invariant Validation
                    │
          ValidatedResolution
                    │
       Timeline Logical Commit CAS
                    │
            persistence COMMIT
                    │
              ExecutionResult
```

Durable Work 不一定通过 `ActionInvocation`；WorkHandler 可以直接产生同一种 `ResolveOutcome`。无论入口来自哪里，**semantic World State mutation** 最终都必须汇聚到：

```text
Resolution -> Runtime Validation -> ValidatedResolution -> Logical Commit
```

World Time advancement 是另一种 Runtime-owned logical transition，不要求先伪造一个 Capability Resolution，但仍必须经过同一 TimelineVersion/CAS authority boundary。

没有 Capability、Agent、Application、Ingress adapter、Boundary、Storage 或 WorkHandler 可以绕过这些 Runtime authority paths。

### 1.1 Execution flow is not Cargo dependency flow

上图表达**运行时调用/数据流**，不是 `Cargo.toml` 依赖图。

Rust 物理依赖以 `governance.md` 为准：

```text
loom-core
   ↑
loom-protocol
   ↑
├──────────────┬──────────────┐
loom-api   loom-capability   loom-agency
      \          |           /
       \         |          /
            loom-runtime
             ↑        ↑
             |        |
       loom-storage  (runtime-backed loom-api implementation)

loom-boundary -> loom-api
```

其中 `A -> B` 在治理文档中明确表示 A depends on B。

### 1.2 Six authority domains

所有 Runtime contract 必须先判断数据属于哪个 domain：

```text
World-level Runtime Metadata
= World identity + World Runtime Binding + Template provenance

World History
= committed Events + frozen Effects

Materialized World State
= Entity / Relationship / Facets

Timeline Logical State
= World Time / logical Work / Work ordering / TimelineVersion / ancestry

Platform Operational State
= lease / fence / retry / process bookkeeping

Platform History / Execution Provenance
= Runtime Revision / Session / ReadSet / implementation evidence
```

不同 domain 不能为了“统一”而共享一个万能 mutation/event/history abstraction。

---

## 2. Identity, Time, Version and Binding Values

### 2.1 Strong IDs

Core 使用不同 newtype 表达不同身份，禁止在公共契约中把所有对象都裸传 `Uuid`/`String`：

```rust
WorldId(Uuid)
TimelineId(Uuid)
EntityId(Uuid)
RelationshipId(Uuid)
EventId(Uuid)
WorkId(Uuid)
ExecutionSessionId(Uuid)
```

语义：

- ID 决定“它是谁”；名称、标签、状态只描述“它现在是什么样”；
- v0 使用 UUIDv7 作为技术身份和数据库索引友好的生成形式；
- UUIDv7 的时间顺序不是 World 历史顺序；
- `EventSeq` 才是某 Timeline 的权威 Event ordering；
- ID 生成属于 Runtime allocator，不属于 Core 隐式系统时钟/随机源。

### 2.2 World Time

```rust
WorldInstant(i64)
WorldDuration(i64)
```

`WorldInstant` 是 Timeline-local 语义时间，不是 UTC timestamp。

- 可以表示现实时间世界、加速世界、tick 世界或虚构历法世界的底层单调坐标；
- `committed_at`、`received_at`、retry backoff 等平台时间不能使用 `WorldInstant`；
- calendar/date/timezone 是 Capability/Application projection，不进入 Core primitive；
- sibling fork Timeline 可以独立推进到不同 `WorldInstant`；
- World Time **不从 Event timestamps 推导**。

World Time 只通过 Runtime authority 的 explicit logical transition 前进：

```text
AdvanceWorldTime(T_current -> T_next)
```

该 transition：

- 必须 monotonic；
- 必须检查 expected TimelineVersion；
- 必须持久化为 reconstructable logical history；
- 必须推进 Timeline logical revision；
- 不需要伪造领域 Event；
- 不能由 PlatformClock / DB NOW / retry / lease 隐式触发；
- **在当前 Timeline 存在 semantically due Pending Work 时禁止执行。**

### 2.3 Timeline Version

```rust
struct TimelineVersion {
    head_event_seq: EventSeq,
    state_revision: StateRevision,
}
```

`TimelineVersion` 是一次 Resolution / logical transition 所依赖的权威 snapshot position。

`state_revision` 的语义必须理解为 **Timeline logical state revision**，而不只是 Facet table revision。

至少以下成功 logical commit 会推进它：

```text
Event / Effect commit
logical Work mutation / current Work completion
World Time advancement
other future reconstructable Timeline logical transitions
```

Platform claim/lease/retry bookkeeping 不推进 TimelineVersion。

- Resolver 读取一个 pinned Base World；
- Commit 使用 expected version 做 CAS；
- 若 Timeline 已变化，ValidatedResolution 不能直接盲写；
- Runtime 按 policy 重新读取并 revalidate/re-resolve，不能把 CAS conflict 冒充 Capability Rejection。

### 2.4 World Runtime Binding

World 必须持有一个持久 execution binding，概念上至少包含：

```text
Capability semantic IDs enabled for this World
compatible version requirements
immutable World-level Capability configuration where genuinely required
binding revision/hash
Template/birth provenance
```

它属于 World-level runtime metadata，并由该 World 所有 Timeline 共享。

必须区分：

```text
Installed Capability
= active software environment contains an implementation

Enabled Capability
= target World Runtime Binding permits the semantic domain
```

以及：

```text
World Runtime Binding
= semantic requirements / permission to execute

Execution Assembly
= exact implementations chosen for one Session
```

World Runtime Binding v0 创建后不可静默修改，也不永久 pin Runtime Revision / exact implementation binary。

---

## 3. Entity, Relationship and Facet

### 3.1 Entity

Entity 是 World identity，不是“大而全的人物对象”。

Core 不内建：年龄、生命值、金钱、职业、情绪、人格等领域状态。

```rust
struct Entity {
    id: EntityId,
    world_id: WorldId,
}
```

同一 World 中 Entity ID 唯一，但一个 Entity 是否存在于某条 Timeline 的当前状态取决于该 Timeline 的历史。Fork 后某分支新创建的 Entity 不自动出现在兄弟分支。

### 3.2 Relationship

Relationship 是有独立 identity、lifecycle 和 state 的 World structural primitive，不是 Entity 上的一个字符串数组。

v0 规则：

- Relationship 支持 N-ary participants；
- participant 有 semantic role；
- participant set 在 Relationship 创建后不可原地改写；
- 主体发生根本变化时结束旧 Relationship，再创建新 Relationship；
- mutable relationship semantics 通过 Relationship Facet 表达。

这样一个 Relationship ID 在历史上始终指向同一结构身份，不会某天代表 Alice↔CompanyA，后一天偷偷变成 Alice↔CompanyB。

### 3.3 Facet

Facet 是 Capability-owned 的 timeline-local composable semantic state。

Rust API 可以统一 owner：

```rust
pub enum FacetOwner {
    Entity(EntityId),
    Relationship(RelationshipId),
}
```

但数据库仍优先使用独立 `entity_facet` / `relationship_facet` 表以保留真实 FK 完整性。

Facet 原则：

- Facet Definition 属于 software/Capability metadata；
- Facet instance value 属于 Materialized World State；
- v0 Effect 使用完整 Facet replacement，不使用通用 JSON Patch；
- 一个 Facet 应保持合理语义边界，不能成为 `everything_about_entity.json`；
- 大型 blob 使用 Object Storage reference，不塞进 Facet。

所有 Entity / Relationship / Facet semantic mutation 必须由 committed Event 的 frozen Effect 解释。

---

## 4. Capability Ownership and World Enablement Contract

> **Capability has semantic power, but never Runtime authority.**

Capability 是一组有唯一所有者的世界语义和解释这些语义的 resolver/validator/handler。它不是服务进程，也不拥有数据库、HTTP endpoint 或网络资源。

### 4.1 Capability Manifest

Manifest 至少表达：

```text
Capability ID
Capability version
required Loom contract/API compatibility
required Capability dependencies
```

`provides` 不需要重复手写，可从实际注册项推导，避免 manifest 与代码漂移。

Manifest/registry 表示 installed software metadata；它不自动赋予所有 World enablement。

### 4.2 Semantic Keys

领域语义使用稳定 semantic key：

```text
identity.person
finance.account
finance.transfer
finance.money_transferred
employment.contract
```

Rust 仍使用不同强类型包装：

```text
FacetTypeId
RelationshipTypeId
EventTypeId
ActionTypeId
WorkHandlerId
```

不能因为底层都可由字符串表示，就在 API 中混用。

### 4.3 Unique Ownership

每一个 semantic type 必须有且只有一个 owning Capability。

Capability registry assembly 时 Runtime 必须拒绝：

- 两个 Capability 注册同一 Facet/Event/Action/Relationship/Handler；
- 缺失 required Capability；
- semantic dependency version 不兼容；
- handler/definition 没有明确 owner。

World Template / Birth Plan 还必须验证目标 World 的 enabled Capability set 对 dependency closure 是完整且 compatible 的。

### 4.4 Installed vs enabled

Runtime 对任何 target-World semantic dispatch 都必须同时满足：

```text
semantic owner exists in installed Execution Assembly
AND
semantic owner is enabled by target World Runtime Binding
```

该检查至少覆盖：

```text
root Action
WorkHandler
Reaction expansion
subresolution
Capability-owned semantic index/retrieval
World-scoped Catalog/discovery
```

> **Registry presence never implies World enablement.**

### 4.5 Read Other, Mutate Own

Capability 可以读取已声明依赖且目标 World 启用的其他 Capability 语义，但只能**直接产生自己拥有语义的 mutation**。

例如：

```text
employment.basic
read finance.account                allowed if dependency + World binding permit
PutFacet employment.*               allowed
Create employment.* relationship    allowed
PutFacet finance.account            forbidden
```

跨 Capability mutation 必须通过 Runtime-mediated subresolution 让目标 semantic owner 自己解释并产生 Effects。

### 4.6 Capability exposes semantics, not transport

Capability 可以注册语义：

```text
FacetDefinition
RelationshipDefinition
EventDefinition
ActionDefinition / Resolver
Invariant
WorkHandler
Reaction
```

Capability **禁止**注册或直接对外暴露：

```text
HTTP route/controller
SSE/WebSocket endpoint
gRPC service
CLI engine command that bypasses Loom API
GPUI engine endpoint
public SDK service
```

`finance.basic` 可以拥有 `finance.transfer`，但不能拥有一个绕过 Loom 的 `POST /finance/transfer` public engine API。

> **Extension defines semantics; Loom owns exposure.**

### 4.7 Binding configuration is not hidden domain state

World Runtime Binding 中只有 assembly 所需、World-level immutable、可版本化审计的配置可以存在。

任何希望随世界历史变化的规则、法律、价格、技术状态、角色权限或领域 policy，应进入 normal Event + State semantics，不能藏在 binding config 里绕过 World History。

---

## 5. Capability Registration Nodes

一个 Capability v0 可以注册以下节点。

### 5.1 FacetDefinition

回答“这种状态长什么样”。至少包含：

```text
FacetTypeId
schema revision
JSON Schema 2020-12
owning Capability
```

FacetDefinition 不存 instance data，不执行数据库写入。

### 5.2 RelationshipDefinition

回答“一种 Relationship 的结构约束是什么”。可以声明：

```text
participant role names
role cardinality
minimum/maximum participants
allowed relationship facets
```

Core 只理解 participant/role/cardinality mechanism，不理解 employer、spouse、guild-member 等领域意义。

### 5.3 EventDefinition

回答“一种 Event 的领域 envelope/payload 结构是什么”。可以定义：

```text
payload schema
participant roles
relationship reference roles
scope requirements
schema revision
```

Event Ledger 的存在和 ordering 属于 Core Authority；Event 的领域意义属于 owning Capability。

### 5.4 ActionDefinition / ActionResolver

Action 表示“请求世界规则尝试做什么”。

Resolver：

- 读取 pinned `BaseWorldView`；
- 可以通过 host `ResolutionContext` 发起声明过依赖且 target World enabled 的 subresolution；
- 可以请求 Runtime-controlled Entropy boundary where allowed；
- 返回 `loom-protocol` 的 `ResolveOutcome`；
- 不能写 Storage、Commit、直接修改 Event Ledger；
- 不能推进 World Time；
- 默认不能拿 generic Cognitive/Network/Provider handle。

v0 cognition 的标准路径属于 Agency：

```text
AgentWorldView -> CognitiveExecutor -> Decision -> ActionInvocation
```

而不是把任意 LLM/provider 变成普通 Resolver 的网络依赖。

### 5.5 Invariant

Invariant 只做 read-only validation。

它可以检查自己的 semantic state，也可以读取已声明 dependency 且 World enabled 的 candidate state，但：

- 不能产生 Effect；
- 不能“顺手修正”非法值；
- 只能 Accept 或 Reject candidate；
- 如果 candidate 不合法，应返回明确 violation，让 Resolver/Runtime 决定下一步。

### 5.6 WorkHandler

WorkHandler 是 Durable Work 到期后的 resolution entrypoint，不是自主后台服务。

它与 ActionResolver 一样：

- 只能在 owning Capability 对目标 World enabled 且当前 Execution Assembly 提供 compatible implementation 时执行；
- 读取 BaseWorldView；
- 返回 ResolveOutcome；
- 无数据库句柄；
- 无 Commit 权限；
- 无权把当前 Work 自己标 Completed/Cancelled/Dead；
- 无权推进 World Time。

当前 Work lifecycle 由 Runtime 控制。

### 5.7 Reaction Registration

Reaction 表达“某类已提交 Event 出现后，需要继续评估什么”。

v0 Reaction 不直接产生 Event/Effect。它只能请求 Runtime 创建 Immediate Durable Work，再由正常 Work execution 产生后续 Resolution。

Reaction 只有在 owning/target Capability 对该 World enabled 时才可以扩展；global registry 中有 Reaction 不代表每个 World 都执行它。

这样避免 commit hook 中出现隐形递归事务，并保持 World causal chain 可追踪。

---

## 6. World Views, Resolution Context and Execution Assembly

Capability 能读取 World Truth，不等于 Agent 可以全知。Loom 必须区分三个 View，并把它们放在一个 pinned Execution Session 内。

### 6.1 BaseWorldView

`BaseWorldView` 是一个 pinned `TimelineVersion` 下的 authoritative world snapshot。

主要消费者：ActionResolver / WorkHandler。

它至少提供：

```text
World / Timeline identity
TimelineVersion
current World Time
entity existence
entity facet
relationship + participants + facet
relationship query
Event lookup / causality lookup
semantic retrieval through controlled boundary when defined
```

它不能暴露：

```text
PgPool
SQL
Storage transaction
raw repository implementation
PlatformClock
mutable registry
```

一次 Resolution 期间不能混读 revision 108、109、110 的“拼接世界”。

World Time 对 Capability 是 pinned read-only semantic coordinate。

### 6.2 CandidateWorldView

`CandidateWorldView = BaseWorldView + Mutation Overlay`。

主要消费者：schema validator / Capability invariant / Runtime invariant。

若同一 Resolution 中先把 Alice.balance 从 100 改到 70，后续 validator 读取 Alice.balance 必须看到 70，而不是数据库旧值 100。

> **Candidate state shadows base state.**

World Time 不由 WorldEffect mutation overlay 修改；time advancement 是独立 Runtime logical transition。

### 6.3 AgentWorldView

AgentWorldView 是经过 Observation、Information、Knowledge、Memory、Visibility 和 Context Budget 裁剪后的主观世界。

主要消费者：Agency / Cognitive Executor。

Agent/LLM 永远不能直接收到 authoritative BaseWorldView。

> **World Truth ≠ Information Space ≠ Agent Knowledge.**

### 6.4 ResolutionContext

`ResolutionContext` 是 Capability Extension API 定义的 host-facing port：Resolver 表达“Host 必须提供哪些受控能力”，Runtime 提供具体实现。

它至少允许 Resolver 使用：

```text
Timeline identity
pinned base version
pinned World Time via BaseWorldView
BaseWorldView query boundary
Resolution budget
Runtime-mediated subresolution gateway
explicit Entropy request/sample boundary where policy allows
read-only current Work execution metadata where later required
```

ReadSet recorder 可以由 Runtime implementation 在背后自动记录，不要求 Capability 直接管理 recorder。

`ResolutionContext` 不是数据库 context，也不是 transaction；它属于 `loom-capability` contract，而不是为了方便让 Capability import `loom-runtime`。

它不能提供：

```text
PlatformClock
AdvanceWorldTime authority
raw RNG
raw network/provider client
generic CognitiveExecutor handle
CommitStore / transaction
```

如果未来某类 Resolver 真的需要 external inference，必须新增 architecture-reviewed explicit host service，并定义 provenance/failure/replay/budget semantics。

### 6.5 Execution Session and Execution Assembly

每一个可能形成 World Truth 的 root execution 都必须有一个 Execution Session。

Session 开始时 Runtime 一次性 pin：

```text
target World / Timeline
input TimelineVersion
World Runtime Binding revision/hash
active Runtime Revision
exact compatible Capability implementation set
Execution Policy revision/config
controlled Entropy / Agency services where relevant
```

这些值组成该 Session 的 Execution Assembly。

同一 Session 中：

- root resolver / WorkHandler 与所有 subresolution 使用同一 Runtime Revision；
- exact Capability implementation 不得中途切换；
- registry refresh 不得改变已经开始的 call graph；
- Capability enablement 以 pinned World Runtime Binding 判断；
- 如果 current active software 无法满足 Binding，Session 在产生 World mutation 前失败为 unavailable/incompatible。

---

## 7. ReadSet and Resolution Budget

### 7.1 ReadSet

ReadSet 记录**这一次 Resolution 实际依赖了什么**，不是 Resolver 预先声明的所有可能读取。

> **ReadSet is observed, not predicted.**

它至少要能够未来表达：

```text
point/object read
facet revision read
relationship read
negative read
predicate/range dependency
semantic retrieval dependency
World Time read through pinned snapshot
```

v0 正确性仍由 Timeline-level CAS 保证；ReadSet 第一阶段主要用于：

1. Execution Provenance；
2. 调试“为什么这个 Resolution 得到这个结果”；
3. 为未来 fine-grained validation/concurrency 留下真实依赖事实。

不能把 ReadSet 永久定义成“若干 object IDs”，否则无法表达“查询 active employment，结果为空”这种 negative/predicate dependency。

### 7.2 Capability Dependency vs World Binding vs ReadSet

三者不能混：

```text
Capability Manifest dependency
= 这个 Capability implementation/semantic contract 需要哪些 semantic domains

World Runtime Binding
= 这个 World 允许哪些 semantic domains / compatibility requirements

ReadSet
= 这一次 Resolution 实际读了哪些 World facts/query results
```

一个 dependency 存在不代表目标 World enabled；一个 World enabled 也不表示本次执行实际读取了该 domain。

### 7.3 Resolution Budget

所有 Resolution 都必须可被 Runtime budgeted，避免一个 Capability 无限制遍历几百万 Entity。

预算维度可以包括：

```text
max entities
max relationships
max events
max graph depth
max semantic results
max bytes
deadline
subresolution depth
entropy calls/bytes where applicable
```

具体数值属于 Runtime Policy，不写死进 Core semantic types。

---

## 8. Agency: Decision and ActionInvocation

### 8.1 Intent Is Not a Runtime Type

“Intent”用于描述 Agent 的心理意义即可，不创建通用 Runtime `Intent`/`IntentRequest` 类型。

长期 Desire/Goal 若需要持久存在，应由 Capability State 表达，而不是 Runtime 临时对象。

### 8.2 Decision

Agency 最终只需要表达：

```rust
pub enum Decision {
    Act(ActionInvocation),
    NoAction,
}
```

Decision 属于 `loom-agency`，不是 World Truth。

Cognitive Executor 不能返回 Event、Effect、Resolution 或 World Time transition。

> **Cognition decides what to attempt; Capability decides what that attempt means.**

### 8.3 One Root Action

v0 一个 Decision 只产生一个 root ActionInvocation。

Agent 不提交一个事务数组来决定“这五个 Action 必须原子”。若一个行为本质需要跨语义原子组合，应定义领域 composite Action，并由 Runtime-mediated subresolution 组合。

> **Atomic composition belongs to Capability resolution, not Agent transaction planning.**

### 8.4 ActionInvocation

`ActionInvocation` 属于 `loom-protocol`，是 Runtime/Agency/Capability 之间共享的统一行为执行协议：

```rust
pub struct ActionInvocation {
    pub action: ActionTypeId,
    pub input: serde_json::Value,
}
```

不要在内部执行链再套 `IntentRequest` / `ActionRequest` / `ActionCommand`。

“谁发起调用”属于 ExecutionOrigin/provenance，而不是所有 Action 都强制拥有 `actor: EntityId`。有些行为可能没有人格化 Actor。

### 8.5 ExecutionOrigin

ExecutionOrigin 表达调用来源，例如：

```text
Agent
Application
Ingress
Operator
Runtime
```

它属于 Execution metadata/provenance，不自动成为 Event payload 或 World actor semantics。

---

## 9. ResolveOutcome, Resolution and Rejection

### 9.1 Protocol ownership

以下未受信任执行值属于 `loom-protocol`：

```text
ActionInvocation
ResolveOutcome
Rejection
Resolution
ProposedEvent
NewWork
WorkMutation
```

它们必须能被 Capability/Agency/Runtime 共享，但不能因此被放进 Core，也不能反向要求 Capability 依赖 Runtime。

### 9.2 ResolveOutcome

Resolver/WorkHandler 的领域结果分两类：

```text
Resolved(Resolution)
Rejected(Rejection)
```

系统故障使用 Rust error channel 表达。

因此：

```text
Ok(Rejected)
= Runtime 正常，但当前世界规则拒绝此行为

Err(...)
= implementation/runtime/storage/provider 等执行故障
```

### 9.3 Rejection Is Not Automatically an Event

余额不足、目标不可达、合同状态不允许等可以是 Resolver rejection。

Runtime 不自动创建 `ACTION_REJECTED` Event。

如果某领域认为“拒绝本身成为了世界事实”（例如银行正式拒绝一笔交易），owning Capability 应显式返回包含对应 Event 的 Resolution。

### 9.4 Resolution

```rust
pub struct Resolution {
    pub events: Vec<ProposedEvent>,
    pub work: Vec<WorkMutation>,
}
```

Resolution 是 **untrusted semantic output**：

- 可以有 `0..N Events`；
- 可以创建/取消未来 Work；
- 不能直接 Commit；
- 不能被 Storage 作为裸 persistence commit input；
- 不属于 public Loom API authority contract；
- **不能直接 Advance World Time**。

成功 Resolution 可以是空变化。比如 Work 执行后发现无需改变世界，但当前 Work 仍需要被 Runtime 原子标记 Completed。

### 9.5 ValidatedResolution

`ValidatedResolution` 属于 `loom-runtime`，是 semantic Resolution authority gate 的结果。

只有 Runtime Effect Engine / validation pipeline 能创建它；Capability/Protocol/API 不提供 constructor。

Runtime-owned persistence port 可以接受 `ValidatedResolution`；`loom-storage` 通过实现该 port 消费它，但不能构造它。

不得为了“Storage 也要看到这个类型”把它移动进 `loom-protocol`/`loom-api`。

Validation 至少包括：

```text
World Runtime Binding / owner enablement validation
schema validation
semantic ownership validation
causal DAG validation
ordered Effect structural validation/application to the Event-local candidate
derive the envelope reference view from Event-before structures plus successful current Create Effects
Event participant/Relationship reference validation against that reference view
Capability invariants
Runtime invariants
Work mutation validation
Event occurred_at == pinned World Time validation for v0
```

它表示“有资格尝试 semantic logical Commit”，不表示 Commit 一定成功；Timeline CAS 仍可能冲突。

### 9.6 ExecutionResult and public mapping

Runtime 内部执行最终会形成收敛后的结果，例如：

```text
Committed(event ids, new timeline version)
NoChange
Rejected(code/details)
```

`loom-api` 可以定义稳定的 public response contract，并由 Runtime 将内部结果映射过去。API 不需要暴露 CAS retry、Mutation Overlay、ValidatedResolution 等内部细节。

CAS conflict 通常属于 Runtime retry/re-resolution 流程，不应冒充领域 Rejection。

World Time-only logical transition 的 public/admin result contract 可以与 Action `ExecutionResult` 分离；不要为了复用 DTO 把时间推进伪装成 Capability Action。

---

## 10. ProposedEvent and CommittedEvent

### 10.1 ProposedEvent

`ProposedEvent` 属于 `loom-protocol`，是 Resolution 中尚未成为 World Truth 的 Event candidate。它可以包含：

```text
EventId
event type + schema revision
occurred_at World Time
participants
relationship references
causal references
scope/target references
payload
resolved World Effects
```

v0 `occurred_at` 表示该事实发生时的 pinned Timeline World Time。

它不是：

- WorldClock advancement request；
- source system wall-clock timestamp；
- arbitrary future effective date。

若领域需要 source/effective/historical timestamp，必须使用明确 payload/scope/domain schema 表达。

### 10.2 Committed Event

只有 Timeline transaction 成功以后 Event 才成为 World Truth，并获得 authoritative：

```text
TimelineId
EventSeq
Execution Session / commit provenance link
platform committed_at metadata
```

具体 persisted record/Rust read model 不要求和 ProposedEvent 一一同型。

Committed Event 不负责决定 Timeline 当前 World Time；它记录自己在什么 World Time 成为该 Timeline 的事实。

### 10.3 Event Can Have Zero Effects

Event 是事实，不是“State update wrapper”。一个事实可能值得进入 Ledger，但不需要 materialized state mutation。

### 10.4 No Standalone Semantic World Effect

反方向不成立：WorldEffect 不能独立 Commit。

所有 Entity / Relationship / Facet semantic mutation 必须隶属于 committed Event，保证任何当前 materialized State 变化都能追溯“什么事实导致了它”。

注意：World Time / logical Work 等 Timeline logical transition 不是 `WorldEffect`，它们由 Runtime-owned logical commit contract 管理。

---

## 11. Event Association and Causal Graph

需要关联、索引、因果追踪和完整性保证的 Event 结构必须关系化，而不是只放 JSONB。

### 11.1 EventParticipant

表达 Event 与 Entity 的直接事实关系，并带 role：

```text
sender
receiver
decision_maker
subject
observer-if-event-semantics-require-it
```

大型受影响群体不能无脑展开成数百万 participant rows。

### 11.2 EventRelationshipRef

表达 Event 对某 Relationship 的事实引用，例如“这次 Event 结束了 contract R100”。

Event 的 `participants` 与 `relationship_refs` 使用一个独立的 envelope reference view：
它包含 Event 前已有效的结构，以及当前 Event 按 `effects` 列表顺序执行且结构校验
成功的 `CreateEntity`/`CreateRelationship` 所引入的结构。`EndRelationship` 等终止或
破坏性 Effect 仍作用于 post-Event candidate，但不得回溯取消当前 Event 对 Event
前有效 Relationship 的引用资格。因此，一个 Event 可以引用自己刚有效创建的
identity，也可以引用并结束 Event 前已 active 的 Relationship；同一 Event 的
`PutFacet` 等后续 Effect 仍必须遵守列表顺序。当前 Event 不会预见 batch 中后续
Event，Storage hard validation 必须复现同一规则，不能让 Runtime 接受而提交适配器
拒绝。

### 11.3 EventScope

表达 population/group/target 范围。Core 只提供引用 mechanism，群体选择器与人口语义由 Capability 定义。

### 11.4 CausalLink

Event causality 形成 Timeline causal DAG。

v0 约束：一个 Event 只能引用：

- 当前 Timeline ancestry 中已存在的 Event；或
- 同一 Commit Batch 中排在它之前的 Event。

不能形成 causal cycle。

World Event Graph 只描述世界事实因果；Resolution call graph / Work / Session / World Time logical transitions 属于其他 execution/history domain，不混入 World causal graph。

---

## 12. WorldEffect and Effect Engine

### 12.1 Minimal WorldEffect

v0 WorldEffect 属于 `loom-core`，保持少而机械：

```rust
pub enum WorldEffect {
    CreateEntity { entity_id: EntityId },
    PutFacet { owner: FacetOwner, facet_type: FacetTypeId, schema_revision: SchemaRevision, value: Value },
    RemoveFacet { owner: FacetOwner, facet_type: FacetTypeId },
    CreateRelationship { relationship_id: RelationshipId, relationship_type: RelationshipTypeId, participants: Vec<RelationshipParticipant> },
    EndRelationship { relationship_id: RelationshipId },
}
```

Core 不出现：

```text
TransferMoney
DamageCharacter
FireEmployee
FallInLove
PublishNews
AdvanceWorldTime
LeaseWork
RetryWork
```

前五类是 Capability semantics，Resolver 把它们解算成 Event + mechanical Effects；后三类属于 Runtime logical/operational authority，不是 semantic WorldEffect。

### 12.2 Full Facet Replacement

v0 `PutFacet` 写入完整 candidate Facet value，而不是通用 JSON Patch。

原因：

- validation 面对完整语义对象更明确；
- replay 更直接；
- Storage 未来仍可内部优化成局部 SQL/JSONB write；
- 若一个 Facet 大到完整 replacement 不合理，应优先重新评估其语义边界。

### 12.3 Effect Engine

Effect Engine 属于 `loom-runtime`，负责：

```text
check target World Binding / semantic enablement
check ownership and schemas
validate each Event's Effects and apply them in listed order
derive the envelope reference view from Event-before structures plus successful Create Effects
check Event participant/Relationship references against that reference view
construct CandidateWorldView
invoke invariants
produce ValidatedResolution
```

Capability 不拥有 Effect Engine。

---

## 13. Cross-Capability Composition

### 13.1 Runtime-Mediated Subresolution

Capability A 需要修改 Capability B 的语义时，不能直接写 B 的 Facet。

正确路径：

```text
Capability A Resolver
        │
        └─ request Action B through ResolutionContext
                    │
                 Runtime host
                    │
     check World Binding + dependency + budget
                    │
            Capability B Resolver
                    │
              B-owned Effects
```

Runtime 最终可以把多个 subresolution 的 Events/Effects 合并成一个原子 ValidatedResolution/Commit。

### 13.2 Resolution Call Graph

跨 Capability 调用形成 Resolution Call Graph，用于：

```text
provenance
budget accounting
cycle detection
max depth
observability
```

它不属于 World Event causal graph。

### 13.3 Recursion

v0 默认禁止同一路径重复进入相同 `(Capability, Action)` 所形成的无界递归。Runtime 必须维护 call stack/depth/budget，并检测明显 cycle。

### 13.4 Root execution state and composition

每个 root Action/Work execution 由 Runtime 持有一份内部执行状态，至少包括：

```text
ExecutionSessionId
pinned World Runtime Binding ref/hash
pinned Runtime Revision / exact implementation assembly
(Capability, Action) call stack       path-local cycle guard
subresolution depth/count             Runtime budget usage
ordered owner-tagged Resolution segments
independent Resolution call-provenance edges
```

每次 `ResolutionContext::subresolve` 必须先通过 Runtime 校验：

```text
child Action input
semantic owner is enabled by target World Binding
child implementation exists in pinned Execution Assembly
manifest dependency authorization
depth/count/cycle budget
```

同 owner 调用允许跨语义调用，跨 owner 调用必须由 caller Capability manifest 直接声明 target owner dependency。重复 pair、超出 depth/count budget 或其他 routing/auth failure 都发生在 child dispatch 和 commit eligibility 之前。

Child `Resolved` 只能由 Runtime 捕获为带 owner 的 untrusted segment；Capability 不能直接合并或重新标记该 segment。Child `Rejected` 是正常 semantic outcome，原样返回父 resolver，不自动升级成 Runtime error，也不产生 segment。

Root 成功后，Effect Engine 按 Runtime 观察到的 segment 顺序在一个共享 `CandidateWorldView` 上逐段验证，并 flatten 成一个 Runtime-owned `ValidatedResolution`。任一 segment validation 或 aggregate budget failure 都不能产生 commit token；成功组合最终只调用一次 Runtime-owned logical commit persistence boundary，Timeline `TimelineVersion` CAS 仍是唯一业务线性化点。

Resolution call-provenance edges 只属于 Execution Provenance。它们不能写入 `ProposedEvent` 的 World causality、participants、Work origin 或其他 Event graph 结构；World Event causal links 仍只表达世界事实之间的因果关系。

---

## 14. Durable Work, Scheduler and World Time

> **Durable Work represents unresolved future execution, not future truth.**

### 14.1 DurableWork

概念字段：

```text
WorkId
TimelineId
WorkHandlerId
payload + payload schema revision
WorkSchedule / effective due World Time
logical schedule order
causal Event reference
origin Work reference
logical status
```

平台调度 metadata 另外包含：

```text
available_at
claimed_by
claimed_until
claim fence
attempt_count
last_error
created_at
updated_at
```

这些不是 Materialized World State，也不能决定 same-Timeline logical Work ordering。

### 14.2 WorkStatus

v0 持久 logical status 只有：

```rust
Pending
Completed
Cancelled
Dead
```

没有持久 `Running/Retrying/Waiting/Paused`。

### 14.3 Claim Lease

Worker claim 是 lease，不是 semantic/logical status transition。

```text
Pending
→ lease acquired
→ process crashes
→ lease expires
→ still Pending
→ another worker may claim
```

这使 Runtime 可以使用 at-least-once worker execution，同时把 exactly-once world mutation 交给 Timeline Commit/idempotency boundary。

Claim/lease/fence/retry：

- 不推进 TimelineVersion；
- 不进入 logical Work history；
- 不推进 World Time；
- fork 不复制为 semantic future；
- **不能让 later Work 越过 logical head。**

### 14.4 WorkMutation

`WorkMutation` 属于 `loom-protocol`。v0 只需要：

```rust
pub enum WorkMutation {
    Schedule(NewWork),
    Cancel(WorkId),
}
```

`Supersede = Cancel + Schedule`，无需额外 primitive。

当前正在执行的 Work 不能由 Handler 返回 `CompleteSelf`/`CancelSelf`。当前 Work lifecycle 由 Runtime 根据 execution outcome 管理。

### 14.5 WorkSchedule and effective due time

v0 只支持：

```rust
Immediate
At(WorldInstant)
```

不在 Core 中引入 cron、business calendar、monthly/full-moon 等周期 DSL。

周期行为使用 chained Work：当前 Work 成功后按领域语义 Schedule 下一次 Work。

所有 Pending Work 必须具有可比较的 **effective due World Time**：

```text
Immediate
→ effective due = scheduling Logical Commit 的 current World Time

At(T)
→ effective due = T
```

是否物理存成一个字段由实现决定；语义必须可持久、可 replay、可 fork。

### 14.6 World Reschedule vs Technical Retry

必须严格区分：

```text
World-driven future reevaluation
→ create a NEW Work
→ WorkSchedule / effective due World Time
→ new logical schedule order

Technical retry
→ reuse SAME Work
→ attempt_count + available_at backoff
→ Platform Time
→ same semantic due time / same logical order
```

真实服务器重试 30 秒不能自动推动 World Time 30 秒，也不能把当前 Work 排到 later Work 后面。

### 14.7 Completion Atomicity

执行 W100 得到 Event/Effects/New Work 时，必须一个 DB transaction：

```text
verify Timeline CAS + Work claim
verify W100 is still the admitted logical head as required
verify Work owner Capability is enabled in target World Binding
append Events
apply Effects
schedule/cancel Work
allocate deterministic logical schedule order for new Work
mark W100 Completed logically
append logical commit / transitions
advance Timeline version
persist Session/Event provenance linkage as required by provenance contract
COMMIT
```

禁止 Event 已提交但 W100 仍 Pending，导致重启后重复执行同一个世界变化。

### 14.8 Dead and Cancelled

`Dead` / `Cancelled` 是 Timeline Runtime Future State，不自动成为 World Event。

它们改变 Timeline 的 logical future，因此必须经 Runtime-owned Logical Commit 持久化并推进 TimelineVersion；不能通过删除 row、只写 `last_error` 或其他 operational shortcut 让 Pending Work 静默消失。

如果“调度失败/取消”在某个世界中本身需要被主体知道，那必须由明确 Capability Event 表达，不能把平台状态偷偷映射成 World Truth。

### 14.9 Fork

Fork 时 Pending Work 被克隆为 child Timeline 的新 Work identity：

```text
parent W100 -> child W200
```

保留 semantic/origin provenance reference，并保持 inherited Work 的 effective due time 与相对 logical schedule order；后续 logical status 完全 branch-local，lease/fence/retry metadata reset。

Fork 同时复制 fork-point World Time；World Runtime Binding 因属于 World 而继续共享。child Timeline 后续新 Work 的 logical schedule order 必须位于 inherited order high-water mark 之后。

> **Pending Work is inherited on fork, but future outcomes are not.**

### 14.10 Semantic due-ness

必须先判断 **semantic due-ness**，再判断平台是否能 claim。

Work 在 Timeline chronology 上 semantically due 当且仅当：

```text
logical status = Pending
AND
effective_due_world_time <= Timeline.world_time
```

Semantic due-ness 不依赖：

```text
available_at
lease state
attempt_count
worker availability
current process health
compatible implementation currently available or not
```

因此一个 Work 即使处于 technical retry backoff，仍然可能是当前 Timeline 的 due obligation。

### 14.11 Operational claimability

一个 Work 只有在 semantically due 的基础上满足平台条件，才 operationally claimable：

```text
available_at <= PlatformTime.now
no unexpired valid lease
owning Capability enabled by World Runtime Binding
compatible handler implementation exists in the active Runtime Revision / resulting Session assembly
claim/fence policy permits acquisition
```

所以合法状态包括：

```text
semantically due = true
operationally claimable = false
```

Platform ineligibility 可以延迟服务器执行，不能取消 semantic due-ness、改变 logical order 或推进 World Time。

### 14.12 Deterministic logical schedule order

同一 Timeline 的 Scheduler-managed Durable Work 必须具有持久、可重建的逻辑顺序。

概念排序键冻结为：

```text
(effective_due_world_time, logical_schedule_order)
```

`logical_schedule_order` 是 Timeline-local persistent order，不由 `WorkId` 推导。

规则：

1. Schedule 成功进入 Logical Commit 时分配 order；
2. 同一 Logical Commit 产生多个 Work 时，按 validated `WorkMutation` 的稳定顺序分配；
3. 新 Immediate Work 在当前 World Time 获得新的后续 order，不插到同时间已存在 Work 前面；
4. Fork 可换 branch-local WorkId，但必须保留 inherited Work 的相对 order；
5. replay 必须恢复同一 order；
6. v0 不允许未持久的 worker priority 重排同一 Timeline chronology。

明确禁止把以下因素当作 logical order：

```text
PostgreSQL natural row order
UUID / UUIDv7 order
worker race
lease acquisition speed
wall-clock race
HashMap iteration order
```

### 14.13 Head-of-line chronology barrier

在某个 Timeline 上，Scheduler logical head 是排序键最小的 `Pending` Work。

当 head 已经 semantically due：

- 只有该 head 可以被 Scheduler admission/claim；
- later same-time Work 不能先执行；
- future Work 不能越过它；
- head 有有效 lease 时，later Work 仍不能 claim；
- head 处于 retry backoff 时，later Work 仍不能 claim；
- head 暂缺 compatible implementation 时，later Work 仍不能 claim。

不同 Timeline 可以独立、并行调度。

这条 ordering law 约束 Scheduler-managed Durable Work，不在 v0 定义所有外部 Action / Ingress / Operator command 的单一 global total-order queue；其他 root inputs 仍由其显式边界与 Timeline CAS 线性化并记录 provenance。

### 14.14 Due-work quiescence barrier

World Time advancement 前，当前 Timeline 必须 scheduler-quiescent：

```text
no semantically due Pending Work
```

只要存在 semantically due Pending Work：

> **AdvanceWorldTime is forbidden.**

例如：

```text
World Time = T20
W1 effective due = T20
W1 available_at = platform P200
W2 effective due = T30
platform now = P100
```

Runtime 必须保持：

```text
Timeline at T20
W1 remains due logical head
W2 remains future
```

不能因为 W1 暂时不能 claim 就跳到 T30 执行 W2。

### 14.15 Leaving the barrier

head Work 只有在 Runtime-owned Logical Commit 后离开 `Pending`：

```text
Completed
Cancelled
Dead
```

technical retry 不改变 logical status，因此不会解除 barrier。

如果 failure policy 最终决定 `Dead`，必须提交明确 logical transition；如果 missing implementation 只是暂时 incompatibility，则 Timeline scheduler 保持 blocked，直到实现恢复或 Operator 通过受控 Runtime logical operation 改变该 Work 的 logical status。

### 14.16 World Time advancement

Scheduler 不能只“等待 World Time 到达”，否则 future Work 可能永远无法变成 due。

Runtime 必须提供 explicit logical authority transition：

```text
AdvanceWorldTime {
    timeline,
    expected_version,
    from,
    to
}
```

概念规则：

- 实际 advancement 必须 `to > from`；
- success 形成 Timeline logical commit；
- TimelineVersion 递增；
- EventSeq 不因纯时间推进而增加；
- 不创建 fake World Event；
- 必须先验证当前无 semantically due Pending Work；
- crash after advance/before Work execution 是合法可恢复状态；
- Replay/Fork 必须从 logical history 恢复 World Time 与 Work order。

### 14.17 Time advancement policy

Core/Runtime contract 定义 advancement mechanism，但不写死世界“多快运行”。

Runtime/Application policy 可以选择：

```text
manual/external advance
jump to next due Work
paced simulation
real-world mirror mapping
custom policy
```

任何 policy 最后都必须调用同一个 explicit authority transition。

自动推进至少遵守：

1. 当前存在 semantically due Pending Work 时绝不推进；
2. operationally unclaimable 的 due head 阻塞 scheduler progression，不能 skip；
3. 默认 next-due policy 跳到最小 future `effective_due_world_time`；
4. PlatformClock passage 本身永远不是 advancement commit；
5. advance 与之后 Work execution 是两个 durable/restart-safe authority boundaries；
6. restart 后从 deterministic logical head 恢复，而不是重新依赖数据库偶然顺序。

---

## 15. Reaction vs Atomic Composition

这两个必须区分。

### Atomic Composition

“必须同时成为现实”的跨 Capability 语义：

```text
sign_contract
├── employment change
└── signing bonus transfer
```

通过 subresolution 组合为同一个 atomic Commit。

所有参与的 owning Capability 都必须在目标 World Runtime Binding 中 enabled。

### Reaction / Future Work

“事实已经发生以后才继续处理”的行为：

```text
contract_signed Event committed
↓
reaction schedules Immediate onboarding Work
↓
future execution
```

Reaction expansion 仍必须检查 target World Binding；globally installed Reaction 不自动作用于所有 World。

Immediate Reaction Work 在 schedule commit 时获得当前 World Time 的 effective due time 和新的 logical schedule order；它不能通过“插队”模拟 atomicity。

> **Must become real together -> Resolution composition.**
>
> **Handle after reality exists -> Reaction / Durable Work.**

---

## 16. Runtime Validation, Logical Commit and Persistence

### 16.1 Validation Pipeline

```text
Resolution
↓
World Runtime Binding / enabled-owner validation
↓
Event/Action/Work schema validation
↓
semantic ownership validation
↓
Event occurred_at == pinned World Time validation
↓
causal DAG validation
↓
validate and apply the current Event's Effects in listed order
↓
derive envelope reference view from Event-before structures plus successful Create Effects
↓
validate current Event participant/Relationship references against that reference view
↓
CandidateWorldView
↓
Capability invariants
↓
Runtime invariants
↓
ValidatedResolution
```

### 16.2 Corrected mutation law

必须同时保留两条不同规则：

> **No semantic World State mutation without a committed Event.**

> **No Timeline logical-state mutation without a Runtime-owned logical commit.**

因此以下都是合法 logical commit：

```text
Event-only
Event + Work
Work-only
World-Time-only
World Time + other Runtime-owned logical transition where explicitly allowed
```

真正无 Event、无 Work、无 Time、无其他 logical transition 的 `NoChange` 不创建 logical commit，也不推进 TimelineVersion。

### 16.3 Commit Is the Linearization Point

Resolve/Cognition 可以并行且耗时；Commit transaction 必须短。

Semantic Resolution commit：

```text
BEGIN
verify expected TimelineVersion
verify target World Runtime Binding revision/identity as required
verify current Work claim if present
verify scheduler logical-head condition when current execution is Durable Work
allocate EventSeq(s)
append committed Events + normalized associations
apply frozen Effects
apply logical Work mutations
allocate/persist logical schedule order for new Work
complete current Work if applicable
append logical commit / logical transitions
advance Timeline version
persist required Event -> Execution Session provenance links atomically enough to avoid orphan history
COMMIT
```

World-Time-only logical commit：

```text
BEGIN
verify expected TimelineVersion
verify current World Time == expected from
verify no semantically due Pending Work
validate monotonic target
append logical time transition / commit record
advance Timeline logical revision
update materialized Timeline world_time
COMMIT
```

EventSeq 不因 pure time/work-only commit 自动增加。

任一失败全部 rollback。

### 16.4 Logical history authority

Replay/Fork 需要两类 reconstructable authority：

```text
Event Ledger + frozen Effects
→ semantic materialized World State

Timeline Logical Commit Journal
→ World Time + logical Work + logical Work order + logical snapshot position
```

Platform lease/fence/retry/backoff 不进入 logical journal。

Replay 禁止通过：

```text
max(event.occurred_at)
current Work table
Platform timestamps
current Capability resolver
Entropy/Cognition resampling
current database row order
```

来猜历史 snapshot 或 historical Work ordering。

### 16.5 Persistence Port Ownership

Runtime 定义完成上述闭环所需的 persistence ports；`loom-storage` 实现这些 ports。

因此运行时虽然是：

```text
Runtime calls Storage
```

Cargo 必须是：

```text
loom-storage -> loom-runtime
```

而不是 `loom-runtime -> loom-storage`。

Application composition root 负责实例化 concrete Storage 并注入 Runtime。

Persistence I/O port 返回 executor-neutral Future；Runtime 可以 await SQLx 等异步 adapter，但不会把 executor、database handle 或 Future 传给 Capability。Resolver/Invariant/WorkHandler 始终只读取 Runtime 已经 pin 好的内存 `BaseWorldView`，因此 Capability semantic execution 不承担数据库 I/O。

World Runtime Binding persistence/read port 同样应由 Runtime 抽象侧定义，Storage 实现；不要为了存 binding 反向让 Runtime import concrete Storage。

Work claim persistence port 必须能够表达 deterministic logical head / due barrier 语义；不能用一个“随便找一条 `available_at <= now` 的 row”查询替代 Runtime contract。

### 16.6 CAS Conflict

CAS conflict 不是 Capability Rejection。

它表示 Resolution 或 logical transition 基于旧 Timeline snapshot。Runtime 应按 policy 重新读取、revalidate 或 re-resolve，而不是把 stale proposal 强行提交。

若 re-resolution 发生，Entropy reuse/resample policy 必须由显式 Runtime contract 决定并可进入 provenance；不能依赖隐藏 RNG 行为。

---

## 17. Unified Loom API Exposure

> **One engine, one public contract, many semantic extensions.**

`loom-api` 是 Loom 对 Application/transport 的唯一 public consumption contract。

### 17.1 Public path

```text
HTTP / GPUI / CLI / SDK
          ↓
        loom-api
          ↓
   Runtime implementation
          ↓
 load target World Runtime Binding
          ↓
 pinned Execution Assembly / Capability routing
```

Boundary 将 HTTP/SSE/WebSocket 映射到 API；Studio/CLI 消费 API；Capability 只向 Runtime Registry 注册语义。

### 17.2 Public capability domains

API 可以按 Loom engine responsibility 拆分：

```text
World
Timeline
Action
Query
History
Subscription
Catalog / Discovery
Admin / Runtime Control
```

统一 API 不等于一个 God Trait。应按职责拆小 contract。

World Time advancement 是 Runtime/Timeline control，不应伪装成某个领域 Action。具体 public trait/authorization placement 在 API design 中决定，但必须与 ordinary semantic Action authority 分离。

### 17.3 World API vs Admin API

World API 和 Runtime Admin API 都属于 Loom public contract，但必须分开 namespace/authorization boundary。

```text
World API
= interact with / observe World and Timeline

Admin / Runtime Control API
= operate platform/runtime/time/lifecycle according to policy
```

### 17.4 No capability-specific bypass

禁止：

```text
HTTP -> finance resolver
GPUI -> employment crate
CLI -> storage repository
SDK -> ValidatedResolution/CommitStore
Application -> raw world_time column update
```

即使某个 Capability 很常用，也不能因此获得第二套 public surface。

### 17.5 Catalog and discovery

必须区分：

```text
Global Installed Catalog
= active/available software semantics

World-Scoped Catalog
= target World Runtime Binding enabled semantics that current compatible Runtime can expose
```

Loom API 可以统一暴露 Capability/semantic descriptors，使消费者发现：

```text
semantic id
owner capability
schema / schema revision
actions
facets
relationships
events
dependencies
World enablement where target-scoped
```

Schema-driven generic UI/CLI 可以建立在 Catalog 上；定制 UI 仍然通过相同 API 调用。

---

## 18. Provenance Domains and Software Binding

Loom 至少区分四类“为什么/依据”：

### 18.1 World Causality

```text
Event E100 -> Event E200
```

回答“世界里的什么事实导致了后续事实”。属于 World Truth graph。

### 18.2 World Runtime Binding

回答：

```text
这个 World 允许哪些 semantic capability？
需要什么 compatibility/configuration？
哪个 Template/revision 产生了这个 birth contract？
```

它不是 Event causal graph，也不是 exact software provenance。

### 18.3 Execution Provenance

```text
Execution Session
→ target World Runtime Binding hash/revision
→ Runtime Revision
→ exact Capability implementation refs
→ Resolution call graph
→ ReadSet
→ Work / Ingress / Agent origin
→ Entropy/Cognitive references
→ committed Event IDs
```

回答“软件当时如何计算并提交了这些事实”。不属于 World Truth。

### 18.4 Agent Knowledge / Memory Provenance

回答“某 Agent 为什么知道/相信/记住某件事”。属于 Information/Memory Capability domain。

这些 graph/domain 不能用一张万能 graph 混在一起。

### 18.5 Runtime Revision activation

Runtime Revision activation：

- 不创建 World Event；
- 不推进 World Time；
- 不修改 World Runtime Binding；
- 只改变未来 Session 可以绑定的 software implementations。

新 Session 必须满足目标 World Binding compatibility；如果不满足则 execution unavailable，而不是 silently upgrade World。

---

## 19. Persistence Mapping Guidance

本文定义语义，不把 Rust 类型机械映射成一表一类型。v0 数据库至少要能独立表达：

```text
world
world_runtime_binding / equivalent world-level binding metadata

timeline
Timeline logical commit / logical transition history

entity
entity_state / entity_facet

relationship
relationship_participant
relationship_state / relationship_facet

world_event
event_participant
event_relationship
event_causality
event_scope

durable_work logical state + effective due time + logical schedule order
work operational lease/retry metadata

execution_session
runtime_revision
execution provenance relations
```

具体 table name/normalization 在实现阶段决定；这里冻结的是 authority separation。

原则：

- stable/queryable/ref-integrity structure 关系化；
- flexible Capability payload/state 使用 JSONB；
- large immutable content 放 Object Storage；
- embedding 是 pgvector retrieval projection，不是 Event Truth；
- World Time advancement 必须可从 logical history 重建；
- logical Work history/order 与 operational claim/retry metadata 分离；
- WorkId/UUID/DB row position 不是 scheduler order；
- World Runtime Binding 与 exact Runtime implementation provenance 分离；
- Storage schema 可以因性能调整，但不能改变 authority semantics；
- public API 不直接暴露数据库 schema/repository model。

---

## 20. Rust API and Crate Shape Guidance

### 20.1 Avoid Giant Capability Trait

不要把所有能力塞进一个拥有二十个方法的 trait。

建议：

```rust
pub trait Capability {
    fn manifest(&self) -> &CapabilityManifest;
    fn register(&self, registrar: &mut CapabilityRegistrar);
}
```

再注册小职责组件：

```text
FacetDefinition
RelationshipDefinition
EventDefinition
ActionResolver
Invariant
WorkHandler
Reaction
```

是否需要 dyn async dispatch、RPITIT 或其他 Rust 语法策略，在真正实现 object-safety 时决定；不要为了接口草图提前引入 `async-trait`。

### 20.2 Crate placement

强制归属保持：

```text
loom-core
    stable World mechanism / WorldEffect / IDs / World Time values

loom-protocol
    ActionInvocation / Resolution / ResolveOutcome / Rejection
    ProposedEvent / NewWork / WorkMutation

loom-api
    stable public Loom consumption service contracts / public DTOs

loom-capability
    CapabilityManifest / definitions / Resolver / Invariant / WorkHandler
    ResolutionContext host-facing port

loom-agency
    Decision / cognitive executor contracts / Agent context contracts

loom-runtime
    Runtime WorldView implementations / ReadSet / Overlay / EffectEngine
    ValidatedResolution / World Binding enforcement / Execution Assembly
    World-Time logical authority / scheduler chronology / commit orchestration / Runtime persistence ports

loom-storage
    SQLx/PostgreSQL/pgvector/object-store implementations of Runtime ports

loom-boundary
    HTTP/SSE/WebSocket mapping over loom-api
```

`World Runtime Binding` 与 scheduler ordering 的 exact Rust value placement 在实现前按 dependency DAG 决定；不得为了让 API/Storage“方便引用”把 `loom-capability` SPI 或 Runtime authority 移到错误 crate。稳定 public descriptor 与 Runtime internal authority model 可以是不同类型。

### 20.3 Type-System Authority Gates

尽可能让 Rust 类型系统表达权限：

```text
Capability can construct Resolution
Capability cannot construct ValidatedResolution
Capability can read World Time
Capability cannot construct/commit World-Time transition
Storage can consume Runtime authority values through Runtime-owned ports
Storage cannot invent semantic authority or scheduler order
Public API cannot expose ValidatedResolution / raw persistence authority
```

不要只靠注释约定“请不要直接 commit”。

### 20.4 Dependency inversion

以下方向属于 contract：

```text
loom-protocol -> loom-core
loom-api -> loom-core / loom-protocol
loom-capability -> loom-core / loom-protocol
loom-agency -> loom-core / loom-protocol
loom-runtime -> loom-core / loom-protocol / loom-api / loom-capability / loom-agency
loom-storage -> loom-core / loom-runtime
loom-boundary -> loom-api
```

Runtime 在调用层可以使用 Storage/Capability/Agency，但物理依赖通过 ports/SPI 保持无环。

### 20.5 Public API documentation

实现以上类型时，`///` 必须包含语义而非翻译字段名。关键字段也应说明，例如：

```rust
/// Timeline logical version observed when this execution started.
///
/// Commit must revalidate this value. A mismatch may reflect an Event, Work,
/// or World-Time transition and therefore cannot be ignored merely because the
/// Event head did not change.
pub base_version: TimelineVersion,
```

`loom-api` public type 还必须说明它是否稳定暴露给 transport/SDK，以及不得泄漏哪些 internal authority semantics。

---

## 21. v0 Non-Goals

本契约明确不要求第一版实现：

```text
fine-grained MVCC ReadSet validation
arbitrary event matcher DSL
cron scheduler
workflow/BPM engine
microservices
Kafka/NATS/Redis authority queue
dynamic WASM Capability ABI
dedicated graph database
generic graph algorithm framework
vendor LLM SDK contract
Agent omniscient WorldView
multi-action Agent transaction API
automatic rejected-action Event
Capability-specific public transport API
per-module controller/service exposure
Runtime coupled to concrete Storage/HTTP/provider implementation
dynamic per-World Capability hot-plug/migration
generic Cognitive/Network handle in Capability ResolutionContext
implicit Event-derived or PlatformClock-derived World Time
single global total-order queue across every external root input
semantic scheduler priority beyond the frozen v0 Work ordering contract
```

这些只有在真实用例证明现有机制不足时再进入架构评审。

---

## 22. Normative v0 Rules

以下规则视为本文的最小验收摘要：

1. **Capability reads World Truth only through Runtime-controlled views; never Storage directly.**
2. **Agent cognition never receives authoritative BaseWorldView.**
3. **Resolution reads pinned BaseWorldView; invariant validation reads CandidateWorldView.**
4. **ReadSet records actual dependencies; Timeline CAS remains v0 correctness boundary.**
5. **Every semantic type has one owning Capability.**
6. **Installed Capability != enabled Capability for a World.**
7. **World Runtime Binding is World-level, shared by Timelines, and immutable in v0.**
8. **World Runtime Binding stores semantic compatibility/config requirements, not a permanent exact implementation pin.**
9. **Every root semantic execution pins one Execution Session / Execution Assembly.**
10. **A Session never switches Runtime Revision or exact Capability implementation mid-flight.**
11. **Capability may read declared, World-enabled dependencies but directly mutates only semantics it owns.**
12. **Cross-Capability mutation is Runtime-mediated, World-binding-aware and can join one atomic Commit.**
13. **Decision chooses what to attempt; Resolution determines what the attempt means.**
14. **Intent is not a generic Runtime protocol type.**
15. **Resolution is untrusted; ValidatedResolution is Runtime-approved semantic commit input.**
16. **Invariant validates only; it cannot produce or repair Effects.**
17. **Event may have zero Effects; semantic WorldEffect may never commit without Event.**
18. **No semantic World State mutation without a committed Event.**
19. **No Timeline logical-state mutation without a Runtime-owned logical commit.**
20. **World Time is explicit, Timeline-local, monotonic logical state.**
21. **Event occurred_at does not advance World Time; v0 Events occur at pinned World Time.**
22. **Platform Time never implicitly advances World Time.**
23. **TimelineVersion changes for reconstructable logical transitions even when Event head does not.**
24. **Durable Work is unresolved future execution, not future World Truth.**
25. **Claim is a lease, not a persistent logical Work state.**
26. **Semantic Work due-ness depends only on logical status + effective due World Time, never retry/lease/platform availability.**
27. **Operational claimability is separate from semantic due-ness.**
28. **World rescheduling creates new Work; technical retry reuses the same Work with the same logical chronology.**
29. **World schedule uses World Time; retry backoff uses Platform Time.**
30. **Current Work completion is Runtime-owned and atomic with resulting logical Commit.**
31. **v0 WorkMutation only needs Schedule and Cancel.**
32. **Same-Timeline Scheduler Work order is persistent `(effective_due_world_time, logical_schedule_order)`.**
33. **WorkId/UUID, database row order, worker race and lease speed never define scheduler chronology.**
34. **Only the semantically due logical head may be Scheduler-admitted; later Work cannot skip it.**
35. **A semantically due Pending Work is a hard World-Time advancement barrier.**
36. **Retry/backoff, active lease or temporarily missing compatible implementation cannot let later Work or World Time bypass the due head.**
37. **Dead/Cancelled/Completed logical transitions leave the barrier only through Runtime-owned Logical Commit.**
38. **Scheduler must have an explicit World-Time advancement mechanism; waiting for Events is not a complete time model.**
39. **Replay reconstructs semantic State from frozen Event Effects and World Time/logical Work/order from logical history.**
40. **Fork clones fork-point World Time and pending future obligations/order into branch-local logical state while retaining the same World Runtime Binding.**
41. **Event causality is a DAG and is separate from execution call/provenance/time-transition graphs.**
42. **Capability never receives raw Storage, Network, PlatformClock, Random or Commit handles.**
43. **Entropy is host-controlled and provenance-ready; replay never resamples it.**
44. **v0 Cognition is an Agency boundary producing Decision, not a generic Capability Resolver provider handle.**
45. **Every new public Core/Protocol/API/Runtime abstraction carries semantic Rust docs sufficient to recover design intent without chat history.**
46. **Semantic ownership, runtime call flow and Cargo dependency direction are different graphs.**
47. **Capability/Agency depend on Core/Protocol, never Runtime.**
48. **Runtime never depends on concrete Storage/Boundary/Capability/provider implementations.**
49. **Storage implements Runtime-owned persistence ports; Boundary adapts only `loom-api`.**
50. **`loom-protocol` contains untrusted shared execution language, never Runtime authority.**
51. **`loom-api` is the single public Loom consumption contract.**
52. **Capability defines semantics and cannot define its own public HTTP/CLI/UI/SDK exposure.**
53. **ValidatedResolution remains Runtime-owned even when another crate needs to consume it.**
54. **Exact Capability implementation versions belong to Execution Provenance.**
55. **Runtime Revision activation never mutates World History, World Time or World Runtime Binding.**
56. **Architecture changes update governance/contracts before violating implementation is written.**
57. **Architecture CI violations are build failures.**

---

## 23. Architecture Freeze and Re-planning Gate

本架构文档集已经完成 v0 closure review，并以 `world-runtime.md` 与本文为 Runtime authority baseline 冻结。

冻结覆盖：

```text
World Runtime Binding ownership
Installed vs World-enabled Capability semantics
explicit World Time progression
semantic due-ness vs operational claimability
same-Timeline deterministic Durable Work ordering
head-of-line / due-work quiescence barrier
Timeline Logical Commit authority
Execution Session vs Runtime Revision / exact implementation binding
Replay / Fork reconstruction domains
Capability host nondeterminism boundaries
Cargo dependency DAG / authority placement
```

下一阶段可以恢复**规划工作**，但不能直接续跑旧 Roadmap：

1. 先基于本冻结架构重新设计 V0 implementation order；
2. 再重新整理/替换 Issues 与 `docs/tasks`；
3. 最后才恢复代码实现。

任何旧 Issue/Task 与本冻结契约冲突时，以本架构文档为准，旧计划不得反向改变架构。

> **Architecture is frozen; the next step is re-planning, not implementation by inertia.**
