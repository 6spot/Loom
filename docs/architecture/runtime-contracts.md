# Loom v0 Runtime Contracts

> Status: normative technical contract for the first Rust implementation.
>
> 本文详细定义 Loom v0 从“请求一个世界行为”到“世界事实被提交”的运行契约。`core.md` 定义概念边界，`implementation.md` 定义技术基线；本文负责把这些原则落实为可编码、可测试、可审计的 Runtime/Capability 协议。
>
> 本文优先解释**概念语义和所有权**，Rust 代码片段是接口草图，不代表最终语法必须一字不差。若实现细节需要调整，不能静默改变本文已经锁定的 authority、truth、ownership 或 transaction boundary。

## 0. Documentation Contract

Loom 的核心抽象不能只靠名字表达语义。每一个公开的 Core/Runtime/Capability 类型、trait、关键 enum variant 与高风险字段，在代码中都必须使用 Rust doc comments (`///` / `//!`) 说明至少以下内容：

1. **Meaning**：它在 Loom 世界模型中代表什么；
2. **Owner**：哪个 crate / Runtime component 拥有它的解释权；
3. **Truth domain**：它属于 World Truth、Runtime State、Execution Provenance、Agent Knowledge 还是 software metadata；
4. **Input / output boundary**：谁可以创建、读取、修改或消费它；
5. **Forbidden use**：它明确不能被用来做什么；
6. **Relationship**：它与最容易混淆的相邻概念有什么区别；
7. **Persistence**：若持久化，权威位置和生命周期是什么；
8. **Concurrency / version rule**：若涉及 Snapshot、Revision、Commit 或 Retry，必须写清楚一致性规则。

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
/// it into a `ValidatedResolution` before Storage is allowed to persist it.
///
/// Unlike `Decision`, this type contains resolved world semantics. Unlike
/// `ValidatedResolution`, it has not crossed the Runtime authority gate.
pub struct Resolution { /* ... */ }
```

> **Documentation is part of the contract.** Missing semantic documentation on a new public Core/Runtime abstraction is an implementation defect, not optional cleanup.

---

## 1. Runtime Contract Map

Loom v0 的主执行链只有一条权威收敛路径：

```text
Stimulus / Application / Ingress / Durable Work
                    │
             optional Agency
                    │
                 Decision
                    │
            ActionInvocation
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
          Timeline Commit CAS
                    │
            PostgreSQL COMMIT
                    │
              ExecutionResult
```

Durable Work 不一定通过 `ActionInvocation`；WorkHandler 可以直接产生同一种 `ResolveOutcome`。无论入口来自哪里，World mutation 最终都必须汇聚到：

```text
Resolution -> Runtime Validation -> ValidatedResolution -> Commit
```

没有 Capability、Agent、Application、Ingress adapter 或 WorkHandler 可以绕过这条路径。

---

## 2. Identity and Version Value Types

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

`WorldInstant` 是 Timeline 语义时间，不是 UTC timestamp。

- 可以表示现实时间世界、加速世界、tick 世界或虚构历法世界的底层单调坐标；
- `committed_at`、`received_at`、retry backoff 等平台时间不能使用 `WorldInstant`；
- calendar/date/timezone 是 Capability/Application projection，不进入 Core primitive。

### 2.3 Timeline Version

```rust
struct TimelineVersion {
    head_event_seq: EventSeq,
    state_revision: StateRevision,
}
```

`TimelineVersion` 是一次 Resolution 所依赖的权威 Snapshot 版本标识。

- Resolver 读取一个 pinned Base World；
- Commit 使用 expected version 做 CAS；
- 若 Timeline 已变化，ValidatedResolution 不能直接盲写；
- v0 默认重新读取并按策略 revalidate/re-resolve。

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

Facet 是 Capability-owned 的 timeline-local composable state。

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
- Facet instance value 属于 Timeline State；
- v0 Effect 使用完整 Facet replacement，不使用通用 JSON Patch；
- 一个 Facet 应保持合理语义边界，不能成为 `everything_about_entity.json`；
- 大型 blob 使用 Object Storage reference，不塞进 Facet。

---

## 4. Capability Ownership Contract

> **Capability has semantic power, but never Runtime authority.**

Capability 是一组有唯一所有者的世界语义和解释这些语义的 resolver/validator/handler。它不是服务进程，也不拥有数据库或网络资源。

### 4.1 Capability Manifest

Manifest 至少表达：

```text
Capability ID
Capability version
required Loom API version
required Capability dependencies
```

`provides` 不需要重复手写，可从实际注册项推导，避免 manifest 与代码漂移。

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

World Template 装配时 Runtime 必须拒绝：

- 两个 Capability 注册同一 Facet/Event/Action/Relationship/Handler；
- 缺失 required Capability；
- semantic dependency version 不兼容；
- handler/definition 没有明确 owner。

### 4.4 Read Other, Mutate Own

Capability 可以读取已声明依赖的其他 Capability 语义，但只能**直接产生自己拥有语义的 mutation**。

例如：

```text
employment.basic
read finance.account                allowed
PutFacet employment.*               allowed
Create employment.* relationship    allowed
PutFacet finance.account            forbidden
```

跨 Capability mutation 必须通过 Runtime-mediated subresolution 让目标 semantic owner 自己解释并产生 Effects。

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

- 读取 `BaseWorldView`；
- 可以通过 Runtime 发起声明过依赖的 subresolution；
- 可以请求 Runtime-controlled Entropy/Cognition boundary；
- 返回 `ResolveOutcome`；
- 不能写 Storage、Commit、直接修改 Event Ledger。

### 5.5 Invariant

Invariant 只做 read-only validation。

它可以检查自己的 semantic state，也可以读取已声明 dependency 的 candidate state，但：

- 不能产生 Effect；
- 不能“顺手修正”非法值；
- 只能 Accept 或 Reject candidate；
- 如果 candidate 不合法，应返回明确 violation，让 Resolver/Runtime 决定下一步。

### 5.6 WorkHandler

WorkHandler 是 Durable Work 到期后的 resolution entrypoint，不是自主后台服务。

它与 ActionResolver 一样：

- 读取 BaseWorldView；
- 返回 ResolveOutcome；
- 无数据库句柄；
- 无 Commit 权限；
- 无权把当前 Work 自己标 Completed/Cancelled/Dead。

当前 Work 生命周期由 Runtime 控制。

### 5.7 Reaction Registration

Reaction 表达“某类已提交 Event 出现后，需要继续评估什么”。

v0 Reaction 不直接产生 Event/Effect。它只能请求 Runtime 创建 Immediate Durable Work，再由正常 Work execution 产生后续 Resolution。

这样避免 commit hook 中出现隐形递归事务，并保持 World causal chain 可追踪。

---

## 6. World Views and Resolution Context

Capability 能读取 World Truth，不等于 Agent 可以全知。Loom 必须区分三个 View。

### 6.1 BaseWorldView

`BaseWorldView` 是一个 pinned `TimelineVersion` 下的 authoritative world snapshot。

主要消费者：ActionResolver / WorkHandler。

它可以提供受控查询协议，例如：

```text
entity existence
entity facet
relationship + participants + facet
relationship query
Event lookup / causality lookup
semantic retrieval
```

它不能暴露：

```text
PgPool
SQL
Storage transaction
raw repository implementation
```

一次 Resolution 期间不能混读 revision 108、109、110 的“拼接世界”。

### 6.2 CandidateWorldView

`CandidateWorldView = BaseWorldView + Mutation Overlay`。

主要消费者：schema validator / Capability invariant / Runtime invariant。

若同一 Resolution 中先把 Alice.balance 从 100 改到 70，后续 validator 读取 Alice.balance 必须看到 70，而不是数据库旧值 100。

> **Candidate state shadows base state.**

### 6.3 AgentWorldView

AgentWorldView 是经过 Observation、Information、Knowledge、Memory、Visibility 和 Context Budget 裁剪后的主观世界。

主要消费者：Agency / Cognitive Executor。

Agent/LLM 永远不能直接收到 authoritative BaseWorldView。

> **World Truth ≠ Information Space ≠ Agent Knowledge.**

### 6.4 ResolutionContext

ResolutionContext 是 Runtime 给 Resolver 的受控执行上下文，至少持有：

```text
Timeline identity
pinned base version
BaseWorldView query boundary
Resolution budget
ReadSet recorder
Runtime-mediated subresolution gateway
explicit Entropy/Cognition access where policy allows
```

它不是数据库 context，也不是 transaction。

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
```

v0 正确性仍由 Timeline-level CAS 保证；ReadSet 第一阶段主要用于：

1. Execution Provenance；
2. 调试“为什么这个 Resolution 得到这个结果”；
3. 为未来 fine-grained validation/concurrency 留下真实依赖事实。

不能把 ReadSet 永久定义成“若干 object IDs”，否则无法表达“查询 active employment，结果为空”这种 negative/predicate dependency。

### 7.2 Capability Dependency vs ReadSet

两者不能混：

```text
Capability Manifest dependency
= 这个 Capability 可能依赖哪些 semantic domains

ReadSet
= 这一次 Resolution 实际读了哪些 World facts/query results
```

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

Decision 属于 Agency，不是 World Truth。

Cognitive Executor 不能返回 Event、Effect 或 Resolution。

> **Cognition decides what to attempt; Capability decides what that attempt means.**

### 8.3 One Root Action

v0 一个 Decision 只产生一个 root ActionInvocation。

Agent 不提交一个事务数组来决定“这五个 Action 必须原子”。若一个行为本质需要跨语义原子组合，应定义领域 composite Action，并由 Runtime-mediated subresolution 组合。

> **Atomic composition belongs to Capability resolution, not Agent transaction planning.**

### 8.4 ActionInvocation

Runtime 的统一行为协议：

```rust
pub struct ActionInvocation {
    pub action: ActionTypeId,
    pub input: serde_json::Value,
}
```

不要再套 `ActionRequest` / `ActionCommand`。

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

### 9.1 ResolveOutcome

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

### 9.2 Rejection Is Not Automatically an Event

余额不足、目标不可达、合同状态不允许等可以是 Resolver rejection。

Runtime 不自动创建 `ACTION_REJECTED` Event。

如果某领域认为“拒绝本身成为了世界事实”（例如银行正式拒绝一笔交易），owning Capability 应显式返回包含对应 Event 的 Resolution。

### 9.3 Resolution

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
- 不能被 Storage 接口接受为持久化输入。

成功 Resolution 可以是空变化。比如 Work 执行后发现无需改变世界，但当前 Work 仍需要被 Runtime 原子标记 Completed。

### 9.4 ValidatedResolution

`ValidatedResolution` 是 Runtime authority gate 的结果。

只有 Runtime Effect Engine / validation pipeline 能创建它；Capability API 不提供 constructor。

Storage commit contract 接受 `ValidatedResolution`，不接受裸 `Resolution`。

Validation 至少包括：

```text
schema validation
semantic ownership validation
identity/reference validation
relationship structure validation
causal DAG validation
candidate Effect application
Capability invariants
Runtime invariants
Work mutation validation
```

它表示“有资格尝试 Commit”，不表示 Commit 一定成功；Timeline CAS 仍可能冲突。

### 9.5 ExecutionResult

调用方最终看到的是收敛后的执行结果，例如：

```text
Committed(event ids, new timeline version)
NoChange
Rejected(code/details)
```

CAS conflict 通常属于 Runtime retry/re-resolution 流程，不应冒充领域 Rejection。

---

## 10. ProposedEvent and CommittedEvent

### 10.1 ProposedEvent

ProposedEvent 是 Resolution 中尚未成为 World Truth 的 Event candidate。它可以包含：

```text
EventId
event type + schema revision
occurred/effective World Time
participants
relationship references
causal references
scope/target references
payload
resolved World Effects
```

### 10.2 CommittedEvent

只有 Timeline transaction 成功以后 Event 才是 CommittedEvent，并获得 authoritative：

```text
TimelineId
EventSeq
commit provenance
platform committed_at
```

### 10.3 Event Can Have Zero Effects

Event 是事实，不是“State update wrapper”。一个事实可能值得进入 Ledger，但不需要 materialized state mutation。

### 10.4 No Standalone World Effect

反方向不成立：WorldEffect 不能独立 Commit。

所有 World State mutation 必须隶属于 committed Event，保证任何当前状态变化都能追溯“什么事实导致了它”。

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

### 11.3 EventScope

表达 population/group/target 范围。Core 只提供引用 mechanism，群体选择器与人口语义由 Capability 定义。

### 11.4 CausalLink

Event causality 形成 Timeline causal DAG。

v0 约束：一个 Event 只能引用：

- 当前 Timeline ancestry 中已存在的 Event；或
- 同一 Commit Batch 中排在它之前的 Event。

不能形成 causal cycle。

World Event Graph 只描述世界事实因果；Resolution call graph / Work / Session 属于 Execution Provenance，不混入 World causal graph。

---

## 12. WorldEffect and Effect Engine

### 12.1 Minimal WorldEffect

v0 WorldEffect 保持少而机械：

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
```

这些是 Capability semantics，Resolver 把它们解算成 Event + mechanical Effects。

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
apply Effects to candidate overlay
check ownership
check references
validate schemas
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
                 Runtime
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

---

## 14. Durable Work

> **Durable Work represents unresolved future execution, not future truth.**

### 14.1 DurableWork

概念字段：

```text
WorkId
TimelineId
WorkHandlerId
payload + payload schema revision
optional due_world_time
causal Event reference
origin Work reference
status
attempt_count
```

平台调度 metadata 另外包含：

```text
available_at
claimed_by
claimed_until
last_error
created_at
updated_at
```

这些不是 World State。

### 14.2 WorkStatus

v0 持久状态只有：

```rust
Pending
Completed
Cancelled
Dead
```

没有持久 `Running/Retrying/Waiting/Paused`。

### 14.3 Claim Lease

Worker claim 是 lease，不是 semantic status transition。

```text
Pending
→ lease acquired
→ process crashes
→ lease expires
→ still Pending
→ another worker may claim
```

这使 Runtime 可以使用 at-least-once worker execution，同时把 exactly-once world mutation 交给 Timeline Commit/idempotency boundary。

### 14.4 WorkMutation

v0 只需要：

```rust
pub enum WorkMutation {
    Schedule(NewWork),
    Cancel(WorkId),
}
```

`Supersede = Cancel + Schedule`，无需额外 primitive。

当前正在执行的 Work 不能由 Handler 返回 `CompleteSelf`/`CancelSelf`。当前 Work lifecycle 由 Runtime 根据 execution outcome 管理。

### 14.5 WorkSchedule

v0 只支持：

```rust
Immediate
At(WorldInstant)
```

不在 Core 中引入 cron、business calendar、monthly/full-moon 等周期 DSL。

周期行为使用 chained Work：当前 Work 成功后按领域语义 Schedule 下一次 Work。

### 14.6 World Reschedule vs Technical Retry

必须严格区分：

```text
World-driven future reevaluation
→ create a NEW Work
→ due_world_time

Technical retry
→ reuse SAME Work
→ attempt_count + available_at backoff
→ Platform Time
```

真实服务器重试 30 秒不能自动推动 World Time 30 秒。

### 14.7 Completion Atomicity

执行 W100 得到 Event/Effects/New Work 时，必须一个 DB transaction：

```text
verify Timeline CAS + Work claim
append Events
apply Effects
schedule/cancel Work
mark W100 Completed
advance Timeline
COMMIT
```

禁止 Event 已提交但 W100 仍 Pending，导致重启后重复执行同一个世界变化。

### 14.8 Dead and Cancelled

`Dead` / `Cancelled` 是 Runtime Future State，不自动成为 World Event。

如果“调度失败/取消”在某个世界中本身需要被主体知道，那必须由明确 Capability Event 表达，不能把平台状态偷偷映射成 World Truth。

### 14.9 Fork

Fork 时 Pending Work 被克隆为 child Timeline 的新 Work identity：

```text
parent W100 -> child W200
```

保留 origin/provenance reference，但后续状态完全 branch-local。

> **Pending Work is inherited on fork, but future outcomes are not.**

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

### Reaction / Future Work

“事实已经发生以后才继续处理”的行为：

```text
contract_signed Event committed
↓
reaction schedules Immediate onboarding Work
↓
future execution
```

> **Must become real together -> Resolution composition.**
>
> **Handle after reality exists -> Reaction / Durable Work.**

---

## 16. Runtime Validation and Commit

### 16.1 Validation Pipeline

```text
Resolution
↓
Event/Action/Work schema validation
↓
semantic ownership validation
↓
identity/reference validation
↓
relationship structural validation
↓
causal DAG validation
↓
apply Effects to Mutation Overlay
↓
CandidateWorldView
↓
Capability invariants
↓
Runtime invariants
↓
ValidatedResolution
```

### 16.2 Commit Is the Linearization Point

Resolve/Cognition 可以并行且耗时；Commit transaction 必须短。

```text
BEGIN
verify expected TimelineVersion
verify current Work claim if present
allocate EventSeq(s)
append committed Events + normalized associations
apply frozen Effects
apply Work mutations
complete current Work if applicable
advance Timeline head/revision/world time if required
COMMIT
```

任一失败全部 rollback。

### 16.3 CAS Conflict

CAS conflict 不是 Capability Rejection。

它表示 Resolution 基于旧 World snapshot。Runtime 应按 policy 重新读取、revalidate 或 re-resolve，而不是把 stale Resolution 强行提交。

---

## 17. Provenance Domains

Loom 至少区分三类“为什么”：

### 17.1 World Causality

```text
Event E100 -> Event E200
```

回答“世界里的什么事实导致了后续事实”。属于 World Truth graph。

### 17.2 Execution Provenance

```text
Execution Session
→ Resolution call graph
→ ReadSet
→ Runtime Revision
→ Work
→ provider/entropy references
→ committed Event IDs
```

回答“软件当时如何计算并提交了这些事实”。不属于 World Truth。

### 17.3 Agent Knowledge / Memory Provenance

回答“某 Agent 为什么知道/相信/记住某件事”。属于 Information/Memory Capability domain。

三者不能用一张万能 graph 混在一起。

---

## 18. Persistence Mapping Guidance

本文定义语义，不把 Rust 类型机械映射成一表一类型。v0 数据库仍遵循：

```text
world
timeline

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

durable_work

execution_session
runtime_revision
```

原则：

- stable/queryable/ref-integrity structure 关系化；
- flexible Capability payload/state 使用 JSONB；
- large immutable content 放 Object Storage；
- embedding 是 pgvector retrieval projection，不是 Event Truth；
- Storage schema 可以因性能调整，但不能改变 authority semantics。

---

## 19. Rust API Shape Guidance

### 19.1 Avoid Giant Capability Trait

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

### 19.2 Type-System Authority Gate

尽可能让 Rust 类型系统表达权限：

```text
Capability can construct Resolution
Capability cannot construct ValidatedResolution
Storage commit accepts ValidatedResolution only
```

不要只靠注释约定“请不要直接 commit”。

### 19.3 Public API Documentation

实现以上类型时，`///` 必须包含语义而非翻译字段名。关键字段也应说明，例如：

```rust
/// Timeline revision observed when this resolution started.
///
/// Commit must revalidate this value. A mismatch means the resolution may be
/// based on stale World Truth and cannot be persisted without Runtime policy
/// deciding to revalidate or resolve again.
pub base_version: TimelineVersion,
```

---

## 20. v0 Non-Goals

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
```

这些只有在真实用例证明现有机制不足时再进入架构评审。

---

## 21. Normative v0 Rules

以下规则视为本文的最小验收摘要：

1. **Capability reads World Truth only through Runtime-controlled views; never Storage directly.**
2. **Agent cognition never receives authoritative BaseWorldView.**
3. **Resolution reads pinned BaseWorldView; invariant validation reads CandidateWorldView.**
4. **ReadSet records actual dependencies; Timeline CAS remains v0 correctness boundary.**
5. **Every semantic type has one owning Capability.**
6. **Capability may read declared dependencies but directly mutates only semantics it owns.**
7. **Cross-Capability mutation is Runtime-mediated and can join one atomic Commit.**
8. **Decision chooses what to attempt; Resolution determines what the attempt means.**
9. **Intent is not a generic Runtime protocol type.**
10. **Resolution is untrusted; ValidatedResolution is Runtime-approved commit input.**
11. **Invariant validates only; it cannot produce or repair Effects.**
12. **Event may have zero Effects; WorldEffect may never commit without Event.**
13. **Event causality is a DAG and is separate from execution call/provenance graphs.**
14. **Durable Work is unresolved future execution, not future World Truth.**
15. **Claim is a lease, not a persistent Work state.**
16. **World rescheduling creates new Work; technical retry reuses the same Work.**
17. **World schedule uses World Time; retry backoff uses Platform Time.**
18. **Current Work completion is Runtime-owned and atomic with resulting World Commit.**
19. **v0 WorkMutation only needs Schedule and Cancel.**
20. **Fork clones pending future obligations into branch-local Work identities.**
21. **Capability never receives raw Storage, Network, System Clock, Random or Commit handles.**
22. **Every new public Core/Runtime abstraction must carry semantic Rust doc comments sufficient to recover its design intent without reading chat history.**

---

## 22. First Implementation Order

实现不再继续扩充抽象，按最短闭环推进：

```text
1. Core value types
   IDs / WorldInstant / EventSeq / TimelineVersion / semantic IDs

2. Core structural types
   FacetOwner / RelationshipParticipant / Event associations / WorldEffect

3. Runtime semantic output
   ActionInvocation / ResolveOutcome / Resolution / Rejection

4. Runtime authority gate
   BaseWorldView / CandidateWorldView / ResolutionContext / ReadSet / budget
   ValidatedResolution constructor kept Runtime-private

5. Durable Work
   WorkStatus / NewWork / WorkMutation / lease/runtime metadata contracts

6. Capability registration
   Manifest / definitions / resolver / invariant / handler / reaction

7. In-memory validation tests
   ownership, causal DAG, candidate overlay, rejection semantics

8. PostgreSQL persistence
   Timeline CAS + Event/State/Work atomic commit

9. PostgreSQL 18 + pgvector integration tests

10. First minimal Capability vertical slice
```

第一批实现的目标不是覆盖社会世界，而是证明：

> **一个没有领域硬编码的 Runtime，能够让 Capability 在受控读取、受控解算、受控验证和唯一 Commit Authority 下安全改变一个持久 World。**
