# Loom Core v0 Conceptual Closure

> Status: **closure review updated by World Runtime Closure; Core v0 conceptual boundary remains frozen by default after this correction.**
>
> 本文定义 Loom Core 的最小概念闭包。它不是实现规格，而是回答：**哪些机制必须属于 Core，哪些语义必须留在 Capability 之外。**
>
> World Runtime Binding、World Time progression、Logical Commit 与 software execution binding 的完整交叉契约见 `world-runtime.md`。

## 1. Admission Rule

> **Loom Core is a world runtime, not a domain simulation.**

一个概念只有在同时满足以下条件时，才有资格进入 Core：

1. 它跨不同 World 类型普遍存在；
2. 移除它后，持续 World Runtime 无法闭环；
3. 它无法通过现有 Core + Capability 组合表达；
4. 它不要求 Core 理解具体领域语义。

“重要”不等于“属于 Core”。Human、Company、Institution、Goal、Emotion、News、Money、Combat 等都可以非常重要，但仍不属于最小 Kernel。

## 2. Core 的八个职责域

```text
Loom Core
│
├── 1. World & Timeline
├── 2. Identity & Structure
├── 3. State
├── 4. History
├── 5. Time
├── 6. Agency
├── 7. Runtime
└── 8. Capability Host
```

这些职责域内部既包含 **World Primitives**，也包含 **Runtime Facilities / Protocols**。属于 Core 不代表它一定是世界中的一个一等对象或一定物理放在 `loom-core` crate。

### 2.1 World Primitives

主要包括：

```text
World
Timeline
Entity
Actor
Agent
Relationship
State / State Facet instance
Event
Effect
World Time
```

### 2.2 Runtime Facilities / Protocols

主要包括：

```text
World Runtime Binding mechanism
Timeline Logical Commit
Scheduler / Trigger
Durable Work
Execution Policy / Strategy
Cognitive Execution
Rule / Validation Kernel
Ingress
World Change Feed / Feedback
Entropy / controlled nondeterminism
Execution Session / Provenance
Capability Host
```

`World Runtime Binding` 与 `Timeline Logical Commit` 是 closure mechanism，不代表必须创造一个可被领域代码直接操纵的巨大 Core object。

## 3. World & Timeline

World 是长期存在的世界身份与运行边界。

一个 World 除了稳定 identity，还拥有长期的 **World Runtime Binding**：它规定 Runtime 未来允许为该 World 使用哪些 Capability semantic domains。Binding 属于 World-level runtime metadata，不是某条 Timeline 的领域 State，也不是 exact software implementation pin。

Timeline 是一个 World 中的一条权威历史分支。每条 Timeline 只有一份权威 Event Ledger，并拥有自己的 World Time 与 logical future state。

```text
World
├── Runtime Binding        # shared by Timelines
├── Main Timeline
├── Scenario Timeline
└── Counterfactual Timeline
```

Fork 创建新的历史分支，不重写原 Timeline。

### 3.1 Timeline 与 Trajectory

个人、公司、国家等 Entity 不拥有独立权威 Timeline。它们在某条 World Timeline 上拥有自己的 **Trajectory**：权威世界历史关于某个 Identity 的局部投影。

同一个 Event 可以同时关联多个 Entity / Relationship Trajectory，从而形成主体路径之间的交集和因果影响。

> **Timeline is the history of the world; Trajectory is the history of an identity within that world.**

Trajectory 是 Projection / Index，不是第二套 Ledger。

### 3.2 Fork

Fork Point 之前的 committed history 是共享祖先；Fork 时的 materialized State、World Time 和 Pending Work 被继承到新分支，之后各自独立演化。

```text
World Identity        = same
World Runtime Binding = same
Past                  = shared ancestry
Current State         = initially equivalent
World Time            = copied from fork point
Pending Future        = inherited with branch-local Work identity
Future Outcome        = independent
```

Fork 后 Timeline logical state 必须隔离，不能让一个 Timeline 对 Work、World Time 或 State 的变化影响 sibling Timeline。

World Runtime Binding 默认属于 World，不因 Fork 分裂。

## 4. Identity & Structure

### 4.1 Entity Identity

Entity 的核心职责是回答“它是谁”。

Identity 必须由稳定、唯一、不可复用、与名称和可变状态无关的内部 ID 建立。

> **Names describe an identity; they do not create one.**
>
> **ID 决定是谁；名字只是如何称呼它。**

外部身份证号、公司注册号、平台账号等可以作为 External Identity Key / identity evidence，但不替代 Loom 内部 identity。

### 4.2 Identity scope

```text
Global Entity      # optional cross-world identity anchor
      ↓
World Entity       # stable identity in one World
      ↓
Timeline State     # mutable reality in one Timeline
```

> **Identity belongs to World; mutable semantic State belongs to Timeline.**

同一个 World Entity 在不同 Timeline 上仍然是同一个 Identity，只是经历、关系、状态、认知和未来轨迹不同。

### 4.3 Entity / Actor / Agent

Core 只保留少量运行结构角色：

```text
Entity
└── Actor
    └── Agent
```

- **Entity**：稳定可引用并拥有 Timeline-local State 的世界对象。
- **Actor**：可以作为 Intent / Action 的归属主体，不要求自己进行认知计算。
- **Agent**：具有局部认知边界并能够自主形成 Decision / Intent 的 Actor。

Core 不使用 `HUMAN / COMPANY / COUNTRY / MONSTER` 等领域类型驱动 Runtime。

### 4.4 Relationship

Relationship 是独立 Core Primitive，因为它表达多个 Identity 之间持续、可演化、可拥有自身状态与生命周期的结构连接。

Relationship 应拥有稳定 `relationship_id`，支持 participant + role，允许 N-ary 关系；具体 `friend / married / employed_by / owns` 等语义属于 Capability。

## 5. State

Core State 表示某条 Timeline 的当前现实投影。

领域状态通过可组合的 **State Facet** 表达，而不是通过巨大固定 Schema 或领域继承树表达。

```text
Entity / Relationship
└── Timeline Materialized State
    ├── Facet A
    ├── Facet B
    └── Facet C
```

Capability 定义 Facet schema、语义、校验和领域 transition；Core 负责 persistence、revision、Timeline isolation、event-driven mutation、snapshot/projection 和 contract enforcement。

Capability 不能直接修改 State。

### 5.1 Do not call every persisted value “World State”

至少区分：

```text
Materialized World State
= Entity / Relationship / Facets

Timeline Logical State
= World Time / logical Durable Work / logical revision / ancestry

Platform Operational State
= lease / fence / retry / worker bookkeeping
```

Materialized semantic State、Timeline logical state 和 Platform operational state 具有不同 authority rule，不能用一个通用 mutation API 混在一起。

## 6. History: Intent / Event / Effect

Core 的第一运行公理需要精确定义为：

> **No semantic World State mutation without a committed Event.**
>
> Entity / Relationship / Facet 等世界语义状态不能被直接修改；任何这类真实变化都必须先成为该 Timeline 上的 committed history，并由该 Event 的 frozen Effects 解释。

这条原则**不要求**把 World Time advancement、Durable Work lifecycle、fork metadata、lease/retry 等 Runtime-owned state 伪造成领域 Event。

严格区分：

- **Intent**：Actor 想尝试什么；
- **Action Attempt**：一次具体尝试，可被追踪；
- **Event**：Runtime 已承认并提交的世界历史事实；
- **Effect**：该 Event 对 materialized semantic State 的已解析、确定性变化；
- **Logical Transition**：Runtime 对 World Time / logical Work 等 Timeline execution state 的可重建变化；
- **Operational Mutation**：lease/retry 等只服务平台可靠性的变化。

```text
Intent / Proposal
      ↓
    Resolve
      ↓
Resolved Outcome + Effects / Work
      ↓
   Validate
      ↓
Runtime Logical Commit
      ├── append Event(s)
      ├── apply Event Effects
      ├── mutate logical Work
      └── optionally advance World Time
```

Event Ledger append-only。Commit 后 Replay 直接应用 committed Event / Effects，不重新随机、不重新调用模型、不重新决定历史。

Direct Effect 与 downstream Reaction 分离。后续影响通过新的 Work / Intent / Event 形成因果链。

World Event Ledger、Timeline Logical Journal、技术日志、Runtime Audit、Platform Change History 严格分离。

## 7. Time: Past / Present / Future

World Time 是 Timeline-local 的显式语义坐标，不依赖操作系统当前时间，也不由 Event timestamp 反推。

Timeline 运行结构至少分成四类：

```text
Event Ledger           = determined semantic past
Materialized State     = current semantic reality
World Time              = current semantic time coordinate
Durable Work            = unresolved future execution
```

> **A scheduled future is not a future fact.**

Durable Work 只表达“未来需要 Runtime 再处理一次”，不能预先冻结未来结果。

### 7.1 World Time progression

World Time 必须单调，并通过 Runtime authority 的显式 logical transition 前进：

```text
AdvanceWorldTime(T_current -> T_next)
```

不能使用以下隐式模型：

```text
world_time = max(committed_event.occurred_at)
```

否则 Future Work 会出现无法自驱到期的闭环缺口。

World Time advancement：

- 不要求伪造领域 Event；
- 必须持久化为可 replay/fork 的 Timeline logical history；
- 必须参与 TimelineVersion/CAS；
- 不得由 PlatformClock、lease expiry 或 retry backoff 偷偷触发。

新 Event 在 Resolver 所读取的 pinned World Time 上发生；Event timestamp 不能“顺便把 clock 推到未来”。领域 source/effective/historical time 若不同，应由明确领域 semantics 表达。

### 7.2 Durable Work

Durable Work 是某条 Timeline 上持久、可恢复的 Runtime 执行义务。它至少应具备：

- stable work identity；
- Timeline isolation；
- due World Time / trigger；
- handler reference；
- causal / correlation references；
- cancellation / supersession；
- retry / idempotency safety；
- restart safety；
- execution lifecycle；
- budget / priority metadata as needed。

Work 可以重复投递，但 world mutation 不能重复。最终一致性防线仍然是 Runtime Commit。

Logical Work transition 属于 Timeline logical history；claim/lease/retry/backoff 属于 Platform operational state。

### 7.3 Scheduler / Trigger

Scheduler 不理解领域语义，但必须同时处理两个不同问题：

```text
1. current World Time 下是否已有 due Work？
2. 若没有，当前 Runtime/Application policy 是否应该显式推进 World Time？
```

Core 至少支持：

```text
Temporal Trigger  → at/after World Time T
Event Trigger     → when matching committed Event occurs
```

任何自动时间策略最后都必须收敛到同一个 explicit `AdvanceWorldTime` authority transition；不能把 Platform Time 当 WorldClock。

跨时间、多阶段的 `Hiring / Travel / Settlement / Quest / CourtCase` 等 Process 不成为 Core Primitive；Capability 使用 State + Event + Durable Work + Trigger 组合出自己的持续流程。

## 8. Agency

### 8.1 Local cognition boundary

> **World Truth ≠ Agent View.**

Agent cognition 不默认访问 omniscient World State。

```text
World Truth
    ↓
Perception / Access Boundary
    ↓
Agent-local Representation
    ↓
Context
```

Agent-local Representation 可以不完整、过时或错误。

### 8.2 Context

> **Context is budgeted attention.**

Context 是按需构造的有限世界切片，不是 World State 的永久副本。

```text
Actual World Context
      ↓ visibility/access
Agent Context
      ↓ relevance/budget
Cognitive Context
```

Visibility / knowledge eligibility 必须先于 relevance。

### 8.3 Persistent agent-local state

Core 不强制完整的人类 Memory 模型。Core 只保证 Agent 可以拥有跨 Wake 持续存在、Timeline-local、私有且可按预算检索进入 Context 的内部状态。

Episodic memory、semantic memory、consolidation、decay、emotion、personality、goal、need 等具体语义属于 Capability。

### 8.4 Decision and cognition

Core 定义 Decision / Intent 协议，不定义 Agent 为什么行动。

Goal、Need、Policy、Habit、Role Duty、Emotion、External Command 等都可以成为 Capability 提供的 Decision Driver / Bias。

LLM 不等于 Agent。Core 提供 **Cognitive Execution Contract**，官方实现可以提供可配置 `LLM Executor`，也允许其他执行器：

```text
Rule / Policy
Behavior Tree
Small Model
LLM
Human
Hybrid
```

Cognitive Provider 只能基于 Runtime 准备好的受限 Context 产生 Decision / Intent，不能直接读取 World repository、Commit Event 或修改 State。

v0 标准 mutation path 是：

```text
Cognition
  ↓
Decision::Act(ActionInvocation) / NoAction
  ↓
normal Runtime + Capability authority
```

任意 Capability Resolver 默认不获得 generic network/provider handle；如果未来确实需要外部 inference，必须设计新的 explicit host/provenance/replay contract。

## 9. Runtime

Loom Runtime 是 **event-driven + demand-driven + world-time-aware** 的可恢复执行器，而不是固定 Tick 扫描器。

### 9.1 Execution Policy, not fixed pipeline

Core 不规定固定的：

```text
Fast Path → Cognitive Path
```

这只能是一种默认优化策略。

Core 真正提供的是可替换的 **Execution Policy / Strategy**：

```text
Work / Decision Need
        ↓
Execution Policy
        ↓
Deterministic / Policy / Cognition / Composite / Custom
        ↓
Result / Intent / New Work
```

一个 World 可以完全确定性运行，也可以直接使用 Cognition，或采用混合、并行、多阶段执行策略。

World 的运行节奏 policy 与 World Time authority mechanism 分离：Policy 可以决定何时请求 time advancement，但不能绕过 explicit logical transition。

### 9.2 Runtime Authority

只有 Runtime 可以 Commit World Event，也只有 Runtime authority 可以改变 Timeline logical state。

Resolution 可以并行，但 Commit 是 semantic State mutation 的唯一线性化点。并发冲突必须失败、重试或重新 Resolve，不能产生互相矛盾的双重成功。

Timeline logical state 的 World Time / Work transition 同样必须经过 expected TimelineVersion/CAS 的 Runtime-owned logical commit。

Reaction 不得递归直接修改世界，应产生新的 Work 并重新进入 Runtime，受 work/reaction/compute budgets 控制。

### 9.3 Resumability

> **World persists; runtime execution is resumable.**

持续 World 不等于永久 `while(true)` 进程。Materialized State、Timeline logical state、Durable Work 和 Trigger 持久存在；Runtime Compute 可以停止并稍后继续。

World Time advancement 与 Work execution 是可恢复边界：Runtime 可以先持久推进时间，随后崩溃；重启后仍必须从新的 World Time 继续处理 due Work。

## 10. Rule / Validation Kernel

Core 不把所有 Rule 视为“违反即拒绝”。至少区分：

```text
Runtime Invariant
Feasibility / Structural Constraint
Access / Authority / Permission
Law / Policy / Norm
Enforcement / Reaction
```

只有少量 Runtime Invariant 必须阻止 Commit，例如：

```text
identity consistency
Timeline isolation
World Runtime Binding enforcement
World Time monotonicity
Event sequencing
schema integrity
atomicity
referential integrity
```

违法、违规、违背政策或社会规范通常仍然可以成为真实 Event。

Core Rule Kernel 只定义 applicability / evaluation / invariant validation / reaction registration 协议，不理解具体法律、企业制度、社会规范或游戏规则。

Actual Rule 与 Agent Belief About Rule 必须分离。

## 11. Runtime Boundaries

### 11.1 Ingress

Ingress 是外部系统向 Runtime 提交输入的受控边界，不是 World Event。

Core Ingress Protocol 至少需要支持：

```text
identity / idempotency
source / provenance
target World / Timeline
time metadata
handler routing
payload
runtime authorization context
```

Ingress acceptance 只表示 Runtime 接受了输入，不代表输入内容已经成为 World Truth。

Ingress source/platform time metadata 不会自动推进 Timeline World Time。若某种 real-world mirror policy 要将外部时间映射到 World Time，必须通过显式 World Time advancement authority transition。

Capability 负责解释领域语义；Runtime 最终仍通过 Event Commit 改变 semantic World State。

### 11.2 Feedback / World Change Feed

Loom Core 不直接控制现实系统，也不负责执行不可逆外部副作用。

已经 committed 的世界变化可以通过 **World Change Feed** 被 Application / Observer 读取；Capability 或 Application 可以进一步构造 Feedback Projection。

```text
                  External
               ↙            ↖
            Ingress       Feedback
               ↓             ↑
             Runtime → Event ┘
```

Feedback 是只读观察边界，不因 subscriber success/failure 改变 World。如果外部根据反馈决定重新影响 World，应通过新的 Ingress 返回 Runtime。

## 12. Explicit nondeterminism

任何可能影响 World Truth 的不确定来源都必须通过明确的 execution boundary 进入，不能隐藏在 Capability 实现内部。

```text
world time      → explicit Runtime World-Time transition
randomness      → Runtime Entropy Source
external input  → Ingress
cognition       → Agency Cognitive Executor
domain logic    → registered Resolver / Evaluator
```

Capability 不应通过系统时间、隐藏 `random()`、私自模型调用或外部 API 查询偷偷改变 Resolution。

Capability 读取 pinned `BaseWorldView.world_time()`，而不是读取 PlatformClock。

历史确定性来自 committed Event/Effects + Timeline logical history，而不是要求当初的计算过程绝对可重复。

> **Historical replay applies committed history; re-simulation recomputes an alternative future.**

## 13. Execution Session & Provenance

每一个可能形成 World Truth 的 root execution 都形成 **Execution Session**。

Session 开始时至少 pin：

```text
World / Timeline target
input TimelineVersion
World Runtime Binding revision/hash
active Runtime Revision
exact compatible Capability implementation refs
execution policy revision
controlled entropy/cognition environment where used
```

这组冻结值构成该 Session 的 Execution Assembly。

Session 一旦开始不在中途切换 Runtime Revision 或 Capability implementation；subresolution 继承同一 execution environment。

尚未开始的 Durable Work 在真正执行时才绑定当时 active 且满足目标 World Runtime Binding 的 compatible implementations。

Execution Provenance 可以记录：

```text
execution_session_id
runtime_revision
world runtime binding ref/hash
capability implementation refs
execution policy revision
input state revision
world time
ingress / work / agent refs
ReadSet / call graph
entropy refs
cognitive executor refs
result / event refs
```

这些属于 Runtime Audit / operator provenance，默认不进入 Agent Context，也不是 World Event。

软件变化本身记录在独立 Runtime Change Ledger 中。World 不执行“upgrade to revision”；新的执行自然运行在当前已激活且 compatible 的引擎上。

## 14. Capability Host

Extensibility 本身属于 Core，具体领域能力不属于 Core。

Capability Host 最小职责：

```text
Discover installed implementations
Validate registry/dependencies
Bind semantic owner
Enforce target World Runtime Binding
Invoke through controlled host context
Identify exact implementation in Execution Provenance
```

必须明确：

> **Installed Capability != enabled Capability for a World.**

Global registry / active Runtime Revision 表示软件 availability；World Runtime Binding 才表示目标 World 是否允许该 semantic domain。

Capability 可以贡献：

- State Facet Definitions；
- Relationship Definitions；
- Action Definitions；
- Resolvers；
- Rule / Evaluator Definitions；
- Runtime Handlers；
- domain projections / migrations / contracts as needed。

Capability 可以定义世界语义，但绝不能：

- 直接修改 Timeline semantic State；
- 直接推进 World Time；
- 直接写 Event Ledger；
- 绕过 Runtime Commit；
- 私自启动另一个 World loop；
- 越过 Agent cognition boundary；
- 隐藏影响 World Truth 的 nondeterminism；
- 因为“已经安装”就绕过目标 World Binding。

## 15. Closure Review

Core v0 使用四种明显不同的 World 做了反证：

```text
Life Simulation
RPG
Public Opinion / Information World
Mechanical Market Simulation
```

结果：四种 World 都可以由当前 Core 闭环，且没有要求把 Human、Institution、Information Model、Goal、Emotion、Combat、Money、Workflow 或 LLM-specific Agent 等领域概念塞进 Kernel。

本次 World Runtime Closure Review 进一步确认：此前缺失的不是新领域 Primitive，而是两个跨领域运行机制必须显式冻结：

```text
World Runtime Binding
Timeline Logical Commit / explicit World Time progression
```

Review 过程中确认的关键边界：

- `Process` 是 Capability semantic pattern；Core 提供 Durable Work / Trigger。
- External Input 是 Ingress Boundary，不是领域 Primitive。
- LLM 是可配置 Cognitive Executor，不是 Agent 类型。
- `Fast/Cognitive` 是可选执行策略，不是固定线路。
- 外部输出使用 Feedback / Change Feed，不在 Core 中直接执行现实副作用。
- 平台软件历史与 World Timeline 分离，通过 Execution Provenance 关联。
- Runtime 中安装 Capability 不代表所有 World 启用它；World 持有自己的 Runtime Binding。
- World Runtime Binding 表达 semantic requirement，不永久 pin exact software implementation。
- World Time 是 Timeline logical state，必须显式、单调、可重建地推进。
- Event 不负责隐式推动 World Time；Platform Time 更不能推动 World Time。
- `No mutation without Event` 精确收窄为 `No semantic World State mutation without Event`；logical time/work transition 使用 Runtime logical commit。

因此：

> **Loom Core v0 Conceptual Closure Review: PASSED AFTER WORLD RUNTIME CLOSURE CORRECTION.**

从此 Core 默认冻结。新增 Core 概念必须重新通过 Admission Rule；能通过现有 Core + Capability 表达的能力，默认拒绝进入 Kernel。