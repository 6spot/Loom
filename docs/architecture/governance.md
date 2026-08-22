# Loom Architecture Governance

> **Status: normative and mandatory for all Loom development. Updated by World Runtime Closure review.**
>
> 本文定义 Loom 的 Rust 物理依赖、跨 crate contract 所有权、统一对外能力暴露方式以及架构变更流程。它不是设计建议，也不是“推荐实践”。任何实现、重构、Capability、Adapter、Application 或 Agent 生成的代码，只要进入 Loom 仓库，都必须遵守本文。
>
> 若 `implementation.md`、`runtime-contracts.md` 中示意与本文在 **Cargo dependency direction / public exposure / authority type placement** 上发生冲突，以本文为准；概念语义分别以 `core.md`、`world-runtime.md`、`runtime-contracts.md` 为准。

---

## 1. Why This Contract Exists

Loom 同时存在四张图，它们不能混为一谈：

1. **Semantic ownership**：哪个层拥有某个世界概念的解释权；
2. **Runtime call flow**：运行时谁调用谁；
3. **Cargo dependency direction**：Rust 编译时哪个 crate 可以依赖哪个 crate；
4. **Authority / persistence domains**：某个变化属于 World History、Materialized State、Timeline Logical State、Platform Operational State 还是 Platform Provenance。

例如 Runtime 在运行时会调用 PostgreSQL Storage，但这不代表 `loom-runtime` 应该依赖 `loom-storage`。正确方式是 Runtime 定义自己需要的 persistence port，`loom-storage` 依赖 Runtime contract 并实现该 port，由 Application composition root 将两者组装。

同理，Runtime 会调用 Capability Resolver，但 Capability 不应反向依赖 Runtime。Capability Extension API 定义 Resolver 与 Resolver 所需的 host port，Runtime 依赖该 Extension API 并提供实现。

World Runtime Closure 还要求区分：

```text
Installed Capability Registry
= software availability

World Runtime Binding
= target World semantic enablement/compatibility

Execution Assembly
= exact implementations pinned for one Session
```

这些对象即使运行时互相引用，也不能为了方便被塞进同一个低层 shared crate。

> **Runtime call direction may differ from Cargo dependency direction.**
>
> **Persistence location does not determine semantic ownership.**

---

## 2. The Three Core Languages

Loom 的 Rust 实现必须显式区分三个基础语言层。

### 2.1 `loom-core` — World Language

回答：

> **What is a World?**

只承载跨领域、跨运行时实现仍成立的 World mechanism，例如：

```text
World / Timeline identity
Entity / Relationship identity
World Time value types
Event ordering primitives
Facet ownership mechanism
minimal WorldEffect mechanism
hard World invariants
```

重要澄清：

```text
WorldInstant
= stable World Language value

AdvanceWorldTime authority/token/transaction
= Runtime authority
```

不能因为两者都涉及“时间”就把 Runtime control type 塞进 Core。

不得为了“大家都需要这个类型”把执行 DTO、HTTP DTO、Storage DTO、LLM DTO、World Binding persistence row 或 Runtime authority token 塞进 Core。

### 2.2 `loom-protocol` — Internal Execution Language

回答：

> **How do Loom execution components describe an attempt before it becomes reality?**

它是 Runtime、Capability、Agency 之间共享的中立执行语言，只包含**尚未获得 Runtime authority** 的协议值，例如：

```text
ActionInvocation
Resolution
ResolveOutcome
Rejection
ProposedEvent
NewWork / WorkMutation
shared query/value specifications required across execution boundaries
```

`loom-protocol` 不是 Runtime 的子模块，也不是 `common`/`utils` 垃圾桶。

它不能包含：

```text
ValidatedResolution
World-Time commit authority
World Binding persistence authority
CommitStore implementation
PgPool / SQLx types
HTTP handlers
Capability implementation
Cognitive provider implementation
```

Capability `Resolution` 不能通过放一个 `AdvanceWorldTime` variant 来获取 Runtime clock authority。

### 2.3 `loom-api` — Public Consumption Language

回答：

> **How does an Application or external consumer use Loom as one engine?**

它定义 Loom 统一的应用级 contract，而不是任何具体 transport。典型能力域包括：

```text
World
Timeline
Action
Query
History
Subscription
Capability Catalog / Discovery
Runtime / Timeline Control and Administration
```

`loom-api` 可以暴露 stable descriptor/request/result，例如 Template/World Binding summary 或授权的 Timeline time-control request；但不能暴露内部 authority/proposal 细节，例如：

```text
ValidatedResolution
Mutation Overlay
ReadSet recorder
Storage transaction
Capability Resolver object
Work claim lease implementation
World Binding persistence row / mutable registry object
Runtime-internal time commit token
```

> **Core describes the World. Protocol describes execution proposals. API describes how Loom is consumed. Runtime decides what becomes reality.**

---

## 3. Rust Implementation Layers

Loom v0 的物理实现层级固定为：

```text
L0  Kernel
    loom-core

L1  Internal Protocol
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
    cognitive/provider adapters
    concrete Capability implementations

L5  Applications / Composition Roots
    loom-server
    loom-cli
    loom-studio
```

注意：这里的 `L0..L5` 是 **Rust implementation dependency architecture**，不是产品的 `Core → Capability → Template → World → Application` 概念模型，两者服务于不同问题。

`World Runtime Binding` 也不是新的 Rust layer；其 internal authority/enforcement 属于 Runtime execution responsibility，其 public descriptor 若需要则通过 API contract 表达。

---

## 4. Mandatory Cargo Dependency DAG

本节中的：

> **`A -> B` 永远表示 `A` 的 `Cargo.toml` 依赖 `B`。**

禁止用箭头表达运行时调用，避免再次产生歧义。

### 4.1 Framework crate allowlist

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

World Runtime Closure **不改变**这张 DAG。

### 4.2 Concrete extension/adapters

未来的具体 Capability crate：

```text
capabilities/*
-> loom-core
-> loom-protocol
-> loom-capability
```

具体 Cognitive Provider adapter：

```text
adapters/cognitive-*
-> loom-core      (only if stable IDs/value types are genuinely required)
-> loom-protocol  (only if execution protocol values are required)
-> loom-agency
```

它们不得依赖 `loom-runtime` 获得隐藏的 authority。

### 4.3 Applications

`loom-server` 是主要 composition root，可以依赖：

```text
loom-api
loom-runtime
loom-storage
loom-boundary
selected concrete Capability crates
selected cognitive/provider adapters
```

Composition root 负责安装 concrete Capability implementations，但**安装不等于为每个 World 启用**。World enablement 来自 Runtime 读取的持久 World Runtime Binding。

`loom-cli` 与 `loom-studio` 作为 Loom 消费者，默认只面向 `loom-api` 或某个正式 API client adapter；不得为了方便直接穿透到 Capability/Storage/Runtime 内部对象。若存在 embedded/in-process 场景，也必须以 `loom-api` contract 作为它们可见的能力边界。

### 4.4 Forbidden internal edges

以下依赖默认直接视为架构缺陷：

```text
loom-core -> any higher Loom crate
loom-protocol -> loom-runtime / loom-capability / loom-agency / loom-api / adapters
loom-api -> loom-runtime / loom-storage / loom-boundary / concrete capabilities
loom-capability -> loom-runtime / loom-storage / loom-boundary / loom-api
loom-agency -> loom-runtime / loom-storage / loom-boundary / loom-api
loom-runtime -> loom-storage / loom-boundary / concrete capabilities / concrete providers
loom-boundary -> loom-runtime / loom-capability / concrete capabilities
concrete Capability -> loom-runtime / loom-storage / loom-boundary
```

Cargo 本身禁止 dependency cycle；Loom 额外禁止“虽然无环，但越层/反向依赖”的图。

不得为了 World Binding 或 World-Time control 新增反向 dependency。

---

## 5. Dependency Inversion and Port Ownership

一个 port 应放在**需要这个能力的抽象侧**，而不是放在实现侧。

### 5.1 Capability host ports

`loom-capability` 定义：

```text
ActionResolver
Invariant
WorkHandler
Reaction
ResolutionContext (host capability required by resolvers)
```

Runtime 依赖这些 SPI，并实现 Runtime-backed `ResolutionContext`。

因此：

```text
runtime -> capability
capability -X-> runtime
```

Capability 可以要求 Host 提供：

```text
pinned BaseWorldView
subresolution
budget
explicit Entropy request/sample boundary where allowed
```

Capability 不能通过依赖 Runtime concrete type 获得：

```text
Commit authority
AdvanceWorldTime authority
PlatformClock
raw RNG
raw Storage
raw network/provider client
```

v0 cognition 属于 `loom-agency` SPI，不把 generic CognitiveExecutor handle 作为普通 Capability host resource。

### 5.2 Agency ports

`loom-agency` 定义 Cognitive Executor 等 Agency SPI。

具体 provider adapter 实现这些 SPI；Runtime 只依赖 Agency contract，并由 composition root 注入具体实现。

Cognition 标准输出是 Decision（例如 Act/NoAction），不是 Event/Effect/Resolution/World-Time control token。

### 5.3 Runtime persistence/authority ports

Runtime 自己定义它执行闭环所需要的 persistence ports，例如：

```text
WorldStore
World lifecycle / World Runtime Binding store
CommitStore / logical commit authority
Timeline logical history / replay ports
World-Time transition persistence authority
WorkStore / claim contract
Execution provenance / Runtime Revision ports as needed
```

exact split 由实现证据决定，但 ownership 不变。

如果 commit port 需要 `ValidatedResolution` 或 Runtime-internal time transition authority，这些类型继续属于 `loom-runtime`。

`loom-storage` 依赖 Runtime 并实现这些 ports：

```text
loom-storage -> loom-runtime
```

Runtime **不得**：

```rust
use loom_storage::PgStorage;
```

Application composition root 负责把 `PgStorage` 注入 Runtime。

### 5.4 Public Loom API

`loom-api` 定义 Application/transport 可以使用的统一 service contracts。

Runtime 实现这些 contracts：

```text
loom-runtime -> loom-api
```

Transport adapters 只依赖 `loom-api`：

```text
loom-boundary -> loom-api
```

这样 HTTP/SSE/WebSocket adapter 无需知道 Runtime 的内部类型、World Binding storage model 或具体 Capability。

---

## 6. Type Placement Rules

“概念由谁解释”与“共享协议必须放在哪个无环层”要同时满足。

### `loom-core`

```text
WorldId / TimelineId / EntityId / RelationshipId / EventId
WorldInstant / WorldDuration / EventSeq / StateRevision / TimelineVersion
FacetOwner
World structural primitives
WorldEffect (mechanical semantic world mutation primitive)
```

不得放：

```text
AdvanceWorldTime authority token
World Runtime Binding persistence implementation
Execution Assembly
Runtime Revision
```

### `loom-protocol`

```text
ActionInvocation
Resolution
ResolveOutcome
Rejection
ProposedEvent
NewWork
WorkMutation
execution-boundary query/value specifications
```

这些值都还不是 committed World Truth，也不代表 Runtime authority。

`Resolution` 不拥有 World-Time advancement authority。

### `loom-capability`

```text
CapabilityManifest
Capability compatibility/dependency metadata
FacetDefinition
RelationshipDefinition
EventDefinition
ActionDefinition
ActionResolver
Invariant
WorkHandler
Reaction
ResolutionContext port
Capability registrar / registry-facing SPI
```

World Runtime Binding 可以引用 Capability semantic identity/compatibility meaning，但这不代表整个 binding authority/value 必须移动到 `loom-capability`。Runtime internal binding model 与 public descriptors 可以通过转换隔离。

### `loom-agency`

```text
Decision
Agent-facing context contracts
CognitiveRequest / CognitiveResult as needed
CognitiveExecutor SPI
```

`Decision::Act` 可以持有来自 `loom-protocol` 的 `ActionInvocation`，因此 Agency 无需依赖 Runtime。

### `loom-runtime`

```text
ExecutionSession
ExecutionAssembly
World Runtime Binding enforcement / internal authority representation as needed
ReadSet implementation/recorder
ResolutionBudget implementation/policy
Runtime-backed Base/Candidate view implementations
Mutation Overlay
Effect Engine
ValidatedResolution
Timeline logical commit orchestration
World-Time advancement authority/control
Runtime Revision execution state
controlled entropy execution
persistence ports required by Runtime
```

`ValidatedResolution`、World-Time commit authority、World Binding mutation/enforcement authority 都不能因为 Storage/API 需要消费或描述而移动到公共 Protocol/Core。

### `loom-api`

只包含稳定的 Loom consumption contracts 与对外 DTO/descriptor。

API 可以描述：

```text
World/Timeline snapshots
Template selection
World Runtime Binding summary/descriptor
Global vs World-scoped Catalog
Authorized Timeline time-control request/result
```

但不得泄漏：

```text
Runtime binding mutable store object
ExecutionAssembly
ValidatedResolution
logical commit token
Storage row/transaction
```

### `loom-storage`

```text
PgStorage
SQLx repositories/queries
PostgreSQL transaction implementation
pgvector projections
object storage implementation
migrations
```

Storage 可以消费 Runtime-owned persistence port/type，但不能定义 World semantics、World Binding policy 或 World-Time advancement policy。

### `loom-boundary`

```text
HTTP route mapping
JSON transport serialization concerns
SSE
WebSocket when genuinely required
auth/transport middleware where applicable
```

Boundary 只能把 transport 映射到 `loom-api`，不能直接路由到 Capability Resolver、World Binding repository 或 world_time SQL update。

---

## 7. One Public Loom Entry Point

> **Extension defines semantics; Loom owns exposure.**
>
> **Capability 可以扩展 Loom 能做什么，但不能决定 Loom 如何被对外暴露。**

这是强制规则。

### 7.1 Capability may register semantics

Capability 可以注册：

```text
FacetDefinition
RelationshipDefinition
EventDefinition
ActionDefinition / Resolver
Invariant
WorkHandler
Reaction
```

### 7.2 Capability may NOT register exposure

Capability 禁止注册或直接持有：

```text
HTTP route/controller
SSE endpoint
WebSocket endpoint
gRPC service
CLI command
GPUI component as public engine API
public SDK client
raw network listener
```

例如 `finance.basic` 可以注册 `finance.transfer` Action，但不能拥有：

```text
POST /finance/transfer
FinanceController
FinancePublicService
```

### 7.3 External path

所有外部 semantic consumption 统一收敛：

```text
HTTP / GPUI / CLI / SDK / other consumer
                ↓
              Loom API
                ↓
              Runtime
                ↓
       load World Runtime Binding
                ↓
       pinned Execution Assembly
                ↓
        owning semantic resolver
```

禁止：

```text
HTTP -> finance resolver
GPUI -> employment crate
CLI -> storage repository
SDK -> runtime internal commit method
HTTP -> binding table update
CLI -> UPDATE timeline SET world_time = ...
```

> **One engine, one public contract, many semantic extensions.**

---

## 8. Loom API Capability Domains

`loom-api` 应按 Loom 自身的 engine capability 组织，而不是按安装了哪些领域模块组织。

v0 预期能力域：

```text
World API
├── create from Template/Birth contract
├── inspect lifecycle / binding summary

Timeline API
├── inspect / fork
├── inspect World Time
├── authorized explicit World-Time control where exposed

Action API
├── invoke semantic Action
├── inspect Action definition

Query API
├── Entity
├── Relationship
├── Facet/State
├── structural graph queries

History API
├── Event
├── participants / relationships / scopes
├── causal traversal

Subscription API
├── committed World Change Feed

Catalog API
├── global installed semantics where appropriate
├── target World-enabled semantics
├── Actions / Facets / Relationships / Events / Schemas

Admin API
├── pause / resume
├── Durable Work inspect / retry / cancel according to operator policy
├── Runtime Revision
├── migration / health / operational inspection
```

具体 trait 拆分在实现时按职责确定，禁止为了“统一入口”创建一个数百方法的 God Trait。

### 8.1 World API vs Admin / Runtime Control API

二者都属于 Loom，但必须分离 namespace/authorization boundary：

- World API 操作或观察 World/Timeline semantic surface；
- Admin / Runtime Control API 操作 Runtime/platform lifecycle 与受控 Timeline execution mechanics。

Runtime administration、World-Time control 不能伪装成领域 Action；领域 Action 也不能获得平台管理权限。

### 8.2 Capability Discovery

Loom 对外暴露 Capability Catalog/Schema 时必须标明查询域：

```text
Global Installed Catalog
or
World-Scoped Enabled Catalog
```

Consumer 可以动态发现：

```text
semantic id
owning Capability
schema / schema revision
description
required dependencies
available Action definitions
World enablement when target-scoped
```

Studio 可以利用 Schema 自动生成通用表单/检查器；特殊 Application 可以做定制 UI，但最终调用仍必须通过 Loom API。

---

## 9. Transport Is an Adapter, Never the Source of Semantics

HTTP、SSE、WebSocket、CLI 命令格式、GPUI 页面结构都不能定义 World semantics。

例如：

```text
finance.transfer
```

先作为 Capability-owned semantic Action 存在，随后 Boundary 可以把统一 Action API 映射为 HTTP；CLI/Studio 也消费同一个 API。

不能因为前端需要一个按钮，就绕过 Action/Resolver/Runtime 直接写 Facet；不能因为某 Capability 想要“更方便的接口”，就在 Boundary 中为它建立绕过统一 API 的 controller。

同样不能因为 UI 需要“快进到明天”，就由 Boundary/Studio 直接修改 `timeline.world_time`；必须调用正式 Runtime/Timeline control contract。

Transport 可以有协议级差异（HTTP status、SSE reconnect、WebSocket framing），这些差异不得反向污染 Capability 或 Core contract。

---

## 10. Composition Root

只有 Application composition root 负责认识具体实现并把它们连接起来。

例如 `loom-server` 可以知道：

```text
PostgreSQL PgStorage
Runtime
installed Capability implementations
selected Cognitive Executor providers
Entropy implementation
Platform clock
World-time policy implementation/config
HTTP Boundary
```

概念上：

```rust
let storage = PgStorage::connect(...);
let installed_capabilities = assemble_capabilities(...);
let cognition = assemble_cognitive_executors(...);
let time_policy = assemble_world_time_policy(...);

let runtime = Runtime::new(
    storage,
    installed_capabilities,
    cognition,
    /* platform clock, entropy, time policy, ... */
);

let api = runtime.as_loom_api();
serve_http(api);
```

这里的 `installed_capabilities` 只是 software availability；Runtime 仍必须按每个 target World 的持久 Binding 过滤/解析 execution assembly。

具体 API 以后可以使用 `Arc<dyn ...>`、generic composition 或其他 Rust 方式；这里锁定的是 ownership/dependency direction，不提前锁语法。

> **Runtime orchestrates execution; Application wires implementations; World Binding decides semantic enablement.**

---

## 11. Architecture Change Control

### 11.1 Normal feature work cannot change architecture implicitly

普通功能开发不得顺手：

```text
新增反向 crate dependency
让 Capability import loom-runtime
让 Runtime import loom-storage
给某个模块单独开 HTTP route
把 Runtime internal type 暴露成 public API
把 transport DTO 放进 Core
把 global registry 当作 World enablement
用 Event timestamp/PlatformClock 直接推进 World Time
把 Timeline logical transition 伪装成 domain Event
把 lease/retry 记成 World History
把 exact Capability implementation 永久写成 World software pin
```

“这样实现方便”不是架构例外理由。

### 11.2 Required process for an exception

若真实需求证明当前规则不足，必须：

1. 明确描述当前 contract 为什么无法表达该需求；
2. 给出不改变架构的替代方案以及为何不可行；
3. 说明新的依赖/暴露/authority 方式如何避免泄漏与 cycle；
4. **先更新本文以及相关 architecture contract**；
5. 在同一变更中更新 architecture checks / tests；
6. 通过架构评审后再实现业务代码。

不得先提交违例代码，再把文档改成“代码已经这样所以合理”。

### 11.3 Core / Authority changes require stronger review

任何影响以下内容的变更，不属于普通实现细节：

```text
World Truth authority
World Runtime Binding ownership / mutability / scope
World Time progression authority
Timeline Logical Commit linearization point
Capability semantic ownership / World enablement
ValidatedResolution authority gate
World vs Timeline Logical vs Platform Operational State boundary
Execution Session / Runtime Revision binding
public Loom API ownership
Cargo dependency layer boundaries
```

必须回到架构层重新评审。

### 11.4 Architecture closure before issue planning

当 architecture closure review 已经开始时，不得同时继续根据旧 roadmap 扩展实现。

正确顺序：

```text
architecture docs converge
        ↓
manual architecture review passes
        ↓
rebuild implementation plan / Issues / Milestones
        ↓
resume code implementation
```

禁止为了“已有 Issues 已经排好了”而让架构迁就旧计划。

---

## 12. Documentation Requirements

所有新增 crate 必须有 crate-level `//!`，明确：

```text
Responsibility
What it owns
What it does not own
Allowed dependency direction
Public exposure rule
Truth/authority domain
```

所有公开核心抽象继续遵守 `runtime-contracts.md` 的 Documentation Contract：Meaning / Owner / Truth domain / Input-output boundary / Forbidden use / Relationship / Persistence / Concurrency-version rule。

涉及 Binding/Time/Logical Commit 的类型还必须明确：

```text
World-level or Timeline-level?
semantic State or logical State?
reconstructable history or operational metadata?
who may construct/advance/mutate it?
does it affect TimelineVersion/EventSeq?
```

如果一个 reviewer 无法只靠代码注释与 architecture docs 判断“这个类型能不能被某层构造/暴露/提交”，视为文档缺陷。

---

## 13. CI and Machine Enforcement

文档规范不是唯一防线。

CI 必须至少检查：

1. `cargo metadata` / Cargo 本身确认 workspace 无 dependency cycle；
2. workspace internal dependency edge 符合本文件 allowlist；
3. Framework crate 不依赖明确属于其他层的实现 crate；
4. `cargo check / clippy / test` 继续通过。

随着 Capability/Adapter 目录形成，architecture checker 应继续扩展：

```text
Capability crates cannot depend on Runtime/Storage/Boundary
Boundary cannot depend on Runtime/Capability concrete crates
Runtime cannot depend on Storage/Boundary/concrete extensions
transport/database/provider-specific dependency cannot leak into Core/Protocol/API/Capability contracts
```

实现 World Runtime Closure 后，还应通过 contract tests / static checks 尽可能防止：

```text
World execution bypassing Binding
World Time updated without Runtime logical authority
PlatformClock exposed to Capability as World time
raw Runtime authority types leaking through API
```

发现 violation 时 CI 应失败；不得用 ignore/allow 临时绕过而不更新架构规范。

---

## 14. Allowed and Forbidden Examples

### Allowed: Runtime calls Storage through its own port

```text
loom-runtime defines CommitStore / WorldBindingStore / logical time/history ports
loom-storage implements them
loom-server injects PgStorage into Runtime
```

Cargo：

```text
loom-storage -> loom-runtime
```

### Forbidden: Runtime knows PostgreSQL implementation

```text
loom-runtime -> loom-storage
Runtime::new(PgStorage concrete type dependency)
```

### Allowed: Capability asks Host for subresolution/entropy

```text
loom-capability defines ResolutionContext port
loom-runtime implements host behavior
```

### Forbidden: Capability imports Runtime or platform authority

```text
loom-capability -> loom-runtime
finance-basic -> loom-runtime
resolver receives PlatformClock / PgPool / CommitStore
```

### Allowed: Finance registers semantic Action

```text
finance.basic registers finance.transfer
```

### Forbidden: Finance exposes transport

```text
finance.basic registers POST /finance/transfer
finance-basic depends on axum to publish engine API
```

### Allowed: HTTP adapter invokes unified API

```text
HTTP route -> loom-api Action service -> Runtime -> World Binding -> owning Resolver
```

### Forbidden: HTTP adapter routes to a resolver

```text
HTTP route -> finance ActionResolver directly
```

### Allowed: Application requests explicit World-Time control

```text
Application policy
-> loom-api Timeline/Runtime control
-> Runtime AdvanceWorldTime authority
-> Runtime-owned persistence port
-> Storage transaction
```

### Forbidden: Application/Storage invents World Time

```text
UI -> UPDATE timeline SET world_time = NOW()
worker -> world_time += sleep_seconds
storage -> world_time = max(event.occurred_at)
```

### Allowed: Runtime installs many capabilities but World enables a subset

```text
Installed: A B C D
World Binding: A C
Action owned by C -> routable
Action owned by B -> rejected/unavailable for this World
```

### Forbidden: Registry presence becomes authorization

```text
if registry.action(action).is_some() { dispatch }
// without target World Binding check
```

---

## 15. Normative Rules

以下规则视为所有 Loom 开发的强制验收条件：

1. **Semantic ownership, runtime call flow, Cargo dependency direction and authority domains are different graphs.**
2. **Cargo dependencies must remain a DAG and must follow the explicit allowlist.**
3. **`loom-core` is World Language; it is not a shared DTO/authority dumping ground.**
4. **`loom-protocol` contains shared untrusted execution protocol, never Runtime authority.**
5. **`loom-api` is the single public Loom consumption contract.**
6. **Capability and Agency depend on Protocol, never Runtime.**
7. **Runtime depends on abstract contracts, never concrete Storage/Boundary/Capability/provider implementations.**
8. **Persistence ports are owned by Runtime; Storage adapters implement them.**
9. **Transport adapters depend on Loom API and cannot call Capability Resolver or persistence authority directly.**
10. **Capability registers semantics, never HTTP/CLI/GPUI/SDK exposure.**
11. **All external consumers enter through Loom API.**
12. **World API and Runtime/Admin/Timeline-control surfaces are separated by explicit service/authorization boundaries.**
13. **Applications are composition roots; they wire concrete implementations but do not decide per-World semantic enablement by registry presence.**
14. **Installed Capability != enabled Capability for a World.**
15. **World Runtime Binding is World-level and must be enforced by Runtime at every World-scoped semantic dispatch.**
16. **World Runtime Binding does not permanently pin exact Capability implementation; exact implementations belong to Execution Session provenance.**
17. **ValidatedResolution remains Runtime-owned authority and is never moved to shared Protocol for convenience.**
18. **World-Time advancement authority remains Runtime-owned and is never moved into Capability/Protocol/Core merely for reuse.**
19. **World Time is never mutated directly by Boundary/Application/Storage policy; Runtime logical authority is mandatory.**
20. **Timeline logical history, World Event history and Platform operational metadata remain distinct authority domains.**
21. **v0 Capability ResolutionContext exposes controlled host capabilities, not generic network/provider/cognition/platform handles.**
22. **Architecture exceptions require contract change and review before implementation.**
23. **Architecture closure must finish before Issues/Milestones are rebuilt and implementation resumes.**
24. **CI violations are build failures, not optional warnings.**

> **Extension defines semantics; Loom owns exposure.**
>
> **Runtime owns authority; World Binding owns semantic enablement; Session owns exact software binding.**