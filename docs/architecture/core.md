# Loom Core v0 Conceptual Closure

> Status: **closure review passed; Core v0 conceptual boundary frozen by default.**
>
> 本文定义 Loom Core 的最小概念闭包。它不是实现规格，而是回答：**哪些机制必须属于 Core，哪些语义必须留在 Capability 之外。**

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

这些职责域内部既包含 **World Primitives**，也包含 **Runtime Facilities / Protocols**。属于 Core 不代表它一定是世界中的一个一等对象。

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

## 3. World & Timeline

World 是长期存在的世界身份与运行边界。

Timeline 是一个 World 中的一条权威历史分支。每条 Timeline 只有一份权威 Event Ledger。

```text
World
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

Fork Point 之前的 committed history 是共享祖先；Fork 时的逻辑 State 和 Pending Work 被继承到新分支，之后各自独立演化。

```text
Identity       = same existing World identity
Past           = shared ancestry
Current State  = initially equivalent
Pending Future = inherited
Future Outcome = independent
```

Fork 后 Runtime State 必须逻辑隔离，不能让一个 Timeline 对 Work 的取消或修改影响另一个 Timeline。

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

> **Identity belongs to World; mutable State belongs to Timeline.**

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
└── Timeline State
    ├── Facet A
    ├── Facet B
    └── Facet C
```

Capability 定义 Facet schema、语义、校验和领域 transition；Core 负责 persistence、revision、Timeline isolation、event-driven mutation、snapshot/projection 和 contract enforcement。

Capability 不能直接修改 State。

## 6. History: Intent / Event / Effect

Core 的第一运行公理：

> **No mutation without a committed Event.**
>
> 世界状态不能被直接修改；任何真实变化都必须先成为该 Timeline 上的历史。

严格区分：

- **Intent**：Actor 想尝试什么；
- **Action Attempt**：一次具体尝试，可被追踪；
- **Event**：Runtime 已承认并提交的历史事实；
- **Effect**：该 Event 对 Timeline State 的已解析、确定性变化。

```text
Intent / Proposal
      ↓
    Resolve
      ↓
Resolved Outcome + Effects
      ↓
   Validate
      ↓
Atomic Commit
      ↓
Event Ledger
      ↓
Materialized State
```

Event Ledger append-only。Commit 后 Replay 直接应用 committed Event / Effects，不重新随机、不重新调用模型、不重新决定历史。

Direct Effect 与 downstream Reaction 分离。后续影响通过新的 Work / Intent / Event 形成因果链。

World Event Ledger 与技术日志、Runtime Audit、Platform Change History 严格分离。

## 7. Time: Past / Present / Future

Core 使用 WorldClock，不依赖操作系统当前时间作为世界语义。

Timeline 运行结构分成三类：

```text
Event Ledger = determined past
State        = current reality
Durable Work = unresolved future execution
```

> **A scheduled future is not a future fact.**

Durable Work 只表达“未来需要 Runtime 再处理一次”，不能预先冻结未来结果。

### 7.1 Durable Work

Durable Work 是某条 Timeline 上持久、可恢复的 Runtime 执行义务。它至少应具备：

- stable work identity；
- Timeline isolation；
- due time / trigger；
- handler reference；
- causal / correlation references；
- cancellation / supersession；
- retry / idempotency safety；
- restart safety；
- execution lifecycle；
- budget / priority metadata as needed。

Work 可以重复投递，但 world mutation 不能重复。最终一致性防线仍然是 Runtime Commit。

### 7.2 Scheduler / Trigger

Scheduler 不理解领域语义，只负责在 World Time 到达时重新产生 Work。

Core 至少支持：

```text
Temporal Trigger  → at/after World Time T
Event Trigger     → when matching committed Event occurs
```

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

### 9.2 Runtime Commit Authority

只有 Runtime 可以 Commit World Event。

Resolution 可以并行，但 Commit 是 Timeline State mutation 的唯一线性化点。并发冲突必须失败、重试或重新 Resolve，不能产生互相矛盾的双重成功。

Reaction 不得递归直接修改世界，应产生新的 Work 并重新进入 Runtime，受 work/reaction/compute budgets 控制。

### 9.3 Resumability

> **World persists; runtime execution is resumable.**

持续 World 不等于永久 `while(true)` 进程。State、Timeline、Durable Work 和 Trigger 持久存在；Runtime Compute 可以停止并稍后继续。

## 10. Rule / Validation Kernel

Core 不把所有 Rule 视为“违反即拒绝”。至少区分：

```text
Runtime Invariant
Feasibility / Structural Constraint
Access / Authority / Permission
Law / Policy / Norm
Enforcement / Reaction
```

只有少量 Runtime Invariant 必须阻止 Commit，例如身份一致性、Timeline isolation、event sequencing、schema integrity、atomicity、referential integrity。

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

Capability 负责解释领域语义；Runtime 最终仍通过 Event Commit 改变世界。

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

任何可能影响 World Truth 的不确定来源都必须通过明确的 Core execution boundary 进入，不能隐藏在 Capability 实现内部。

```text
world time      → WorldClock
randomness      → Entropy Source
external input  → Ingress
cognition       → Cognitive Executor
domain logic    → registered Resolver / Evaluator
```

Capability 不应通过系统时间、隐藏 `random()`、私自模型调用或外部 API 查询偷偷改变 Resolution。

历史确定性来自 committed Event，而不是要求当初的计算过程绝对可重复。

> **Historical replay applies committed history; re-simulation recomputes an alternative future.**

## 13. Execution Session & Provenance

一次 Work 真正开始处理时形成 **Execution Session**，并绑定当时激活的 Runtime Revision / implementation references。

Session 一旦开始不在中途切换 Runtime Revision；未来尚未开始的 Durable Work 在实际执行时使用当时当前引擎。

Execution Provenance 可以记录：

```text
execution_session_id
runtime_revision
capability implementation refs
execution policy revision
input state revision
world time
ingress refs
entropy refs
cognitive executor refs
result / event refs
```

这些属于 Runtime Audit / operator provenance，默认不进入 Agent Context，也不是 World Event。

软件变化本身记录在独立 Runtime Change Ledger 中。World 不执行“upgrade to revision”；新的执行自然运行在当前已激活引擎上。

## 14. Capability Host

Extensibility 本身属于 Core，具体领域能力不属于 Core。

Capability Host 最小职责：

```text
Discover
Validate
Bind
Invoke
Identify implementation
```

Capability 可以贡献：

- State Facet Definitions；
- Relationship Definitions；
- Action Definitions；
- Resolvers；
- Rule / Evaluator Definitions；
- Runtime Handlers；
- domain projections / migrations / contracts as needed。

Capability 可以定义世界语义，但绝不能：

- 直接修改 Timeline State；
- 直接写 Event Ledger；
- 绕过 Runtime Commit；
- 私自启动另一个 World loop；
- 越过 Agent cognition boundary；
- 隐藏影响 World Truth 的 nondeterminism。

## 15. Closure Review

Core v0 使用四种明显不同的 World 做了反证：

```text
Life Simulation
RPG
Public Opinion / Information World
Mechanical Market Simulation
```

结果：四种 World 都可以由当前 Core 闭环，且没有要求把 Human、Institution、Information Model、Goal、Emotion、Combat、Money、Workflow 或 LLM-specific Agent 等领域概念塞进 Kernel。

Review 过程中确认的关键边界：

- `Process` 是 Capability semantic pattern；Core 提供 Durable Work / Trigger。
- External Input 是 Ingress Boundary，不是领域 Primitive。
- LLM 是可配置 Cognitive Executor，不是 Agent 类型。
- `Fast/Cognitive` 是可选执行策略，不是固定线路。
- 外部输出使用 Feedback / Change Feed，不在 Core 中直接执行现实副作用。
- 平台软件历史与 World Timeline 分离，通过 Execution Provenance 关联。

因此：

> **Loom Core v0 Conceptual Closure Review: PASSED.**

从此 Core 默认冻结。新增 Core 概念必须重新通过 Admission Rule；能通过现有 Core + Capability 表达的能力，默认拒绝进入 Kernel。