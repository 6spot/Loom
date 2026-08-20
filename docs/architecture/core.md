# Loom Core Minimum Closure

> Status: confirmed architectural baseline.
>
> 本文定义 Loom Core 的最小闭包（minimum closure）：如果移除所有具体领域能力，Core 仍必须能够独立承载一个持续存在、可演化、可暂停恢复、可分叉并可被上层扩展的智能世界。

## 1. Core 的定义

> **Loom Core is a world runtime, not a domain simulation.**
>
> **Core 决定世界怎样存在和运行；Capability 决定这个世界会什么、意味着什么；Application 决定用户拿这个世界来做什么。**

Core 的准入标准不是“这个概念是否重要”，而是：

> **如果没有它，一个持续智能世界 Runtime 是否仍然能够闭环？**

如果能够闭环，则该概念原则上不应进入最小 Core，而应由 Capability Module、World Template 或 Application 承担。

## 2. Core 的八个 Kernel Concern

```text
Loom Core
│
├── 1. World & Timeline
│      identity / lifecycle / fork
│
├── 2. Identity & Structure
│      Entity / Actor / Agent / Relationship
│
├── 3. State
│      timeline-local state / facets / revision
│
├── 4. History
│      Event / Ledger / Effect / causality
│
├── 5. Time
│      WorldClock / Scheduler
│
├── 6. Agency
│      local view / context / decision / intent
│
├── 7. Runtime
│      work queue / resolve / evaluate / commit / reaction
│
└── 8. Capability Host
       registration / binding / invocation / semantic extension
```

这些是 Core 的职责域，不要求每个 World 都实际启用其中全部能力。例如，一个纯机械市场 World 可以完全没有 Agent；Agent 是 Core 支持的结构原语，而不是 World 存在的必要条件。

## 3. World & Timeline

World 是长期存在的世界身份与运行边界。

Timeline 是一个 World 中的一条权威历史分支。一个 Timeline 只有一份权威 Event Ledger。

```text
World
├── Main Timeline
├── Scenario Timeline
└── Counterfactual Timeline
```

Fork 创建新的历史分支，但不重写原 Timeline。

### Timeline 与 Trajectory

个人、公司、国家等主体不各自拥有独立的权威 Timeline。

它们在某条 World Timeline 中拥有自己的 **Trajectory**：世界历史关于某一 Identity 的局部轨迹/投影。

```text
World Timeline
├── 张三 Trajectory
├── Company X Trajectory
└── Country A Trajectory
```

同一个 Event 可以同时进入多个 Entity / Relationship Trajectory，因此主体之间通过共享 Event 产生交集和因果影响。

> **Timeline is the history of the world; Trajectory is the history of an identity within that world.**
>
> **Timeline 是世界走过的历史，Trajectory 是一个身份在这段历史中走过的路径。**

Trajectory 不取代、不复制权威 Ledger。

## 4. Identity & Structure

### 4.1 Entity Identity

Entity 的核心职责是回答“它是谁”，而不是承载固定领域 Schema。

Identity 必须具有稳定、唯一、不可复用、与名称和可变状态无关的内部标识。

```text
WorldEntity
- entity_id      # authoritative identity
- provenance
- optional global_entity_ref
- structural role(s)
```

名字、别名、职位、位置、财富、关系等都不能作为身份本身。

> **Names describe an identity; they do not create one.**
>
> **ID 决定“是谁”，名字只是“如何称呼它”。**

### 4.2 Global Entity / World Entity / Timeline State

```text
Global Entity      # optional cross-world identity anchor
      ↓
World Entity       # stable identity inside one World
      ↓
Timeline State     # mutable state on one Timeline
```

同一个 World 的不同 Timeline 共享已有 World Entity Identity，但拥有不同的可变状态、关系、经历和认知轨迹。

> **Identity belongs to World; mutable State belongs to Timeline.**
>
> **身份属于世界，人生属于时间线。**

Fork 时已经存在的 Entity Identity 延续到新 Timeline；Fork 后新产生的 Entity 默认由各自分支的因果历史独立创建，除非显式建立身份对应关系。

### 4.3 Entity / Actor / Agent

Core 只保留 Runtime 必需的结构角色：

```text
Entity
└── Actor
    └── Agent
```

- **Entity**：具有稳定身份、可被引用并拥有 Timeline-local State 的世界对象。
- **Actor**：可以作为 Action/Intent 行动归属主体，但不要求自己进行认知计算。
- **Agent**：具有局部认知边界并能够自主执行感知—判断—Intent 循环的 Actor。

Core 不使用 `HUMAN / COMPANY / COUNTRY / MONSTER` 等领域 Entity Type 作为运行分支条件。

### 4.4 Relationship

Relationship 保留为独立 Core Primitive，因为它表达多个 Identity 之间持续、可演化的结构连接。

Relationship 拥有自己的唯一身份、参与者、角色、生命周期与 Timeline-local State，并应允许 N-ary participant/role 模型；二元 edge 只是特例。

Core 不理解 `friend / married / employed_by / owns` 等具体关系语义，这些由 Capability Module 定义。

## 5. State

Core State 是 Timeline-local 的可变事实投影。

领域状态通过版本化、可验证的 **State Facet** 组合到 Entity 或 Relationship 上，而不是通过巨大固定 Schema 或继承树表达。

```text
Entity / Relationship
└── Timeline State
    ├── Facet A
    ├── Facet B
    └── Facet C
```

Facet Definition 由 Capability 提供，Core 负责：

- persistence；
- revision；
- Timeline isolation；
- event-driven mutation；
- snapshot / projection；
- schema contract enforcement。

Capability 可以定义 State 语义，但不能直接修改 State。

State Facet 可随 committed Event 被 attach / update / end；领域身份和能力因此能够随历史演化，而不是出生时固定。

Core 可支持 stored / derived / materialized projection，但具体推导语义属于 Capability。

## 6. History: Event / Ledger / Effect

Core 的第一运行公理：

> **No mutation without a committed Event.**
>
> **世界状态不能被直接修改；任何真实变化都必须先成为该 Timeline 上的历史。**

严格区分：

- **Intent**：某个 Actor 想尝试什么；
- **Action Attempt**：一次具体尝试，可被追踪；
- **Event**：Runtime 已承认并提交的历史事实；
- **Effect**：该 Event 对 Timeline State 的确定性变化。

```text
Intent
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

Nondeterminism、随机数和模型推理允许发生在 Commit 前；Commit 后的 Event 必须保存已解析结果与 Effects，Replay 不重新随机、不重新调用模型决定历史。

Direct Effect 与 downstream Reaction 分离。一个 Event 的后续社会、经济或认知影响必须通过新的 Work / Intent / Event 继续形成因果链，而不是把整个未来塞进一次 Event。

Event Ledger 与技术日志、调试日志严格分离。

## 7. Time

Core 提供 WorldClock 与 Scheduler。

世界时间不等于操作系统时间，也不要求固定 Tick。

Scheduler 只负责：

> 在 World Time T 到达时，把相应工作重新放入 Runtime。

它不理解“发工资”“复诊”“技能冷却”等领域含义。

当没有有意义的待处理工作时，非实时 World 可以直接推进到下一个有意义的 World Time，而无需空转。

## 8. Agency

### 8.1 Agent-local View

Agent cognition 不能默认访问 omniscient World State。

Core 必须提供：

```text
World Truth
    ↓
Perception / Access Boundary
    ↓
Agent-local Representation
    ↓
Context
```

一个 Agent 可以拥有不完整、过时甚至错误的局部表示。

### 8.2 Context

> **Context is budgeted attention.**

Context 是 Runtime 按需构造的有限世界切片，不是 World State 的副本。

至少应保持：

```text
Actual World Context
      ↓ visibility/access
Agent Context
      ↓ relevance/budget
Cognitive Context
```

Visibility 优先于 Relevance：某个秘密再相关，只要 Agent 不可知，就不能进入它的 Cognitive Context。

Context 可以是多 Facet、重叠且动态变化的；普通 Context 是临时 Runtime 投影，而不是永久维护的大对象。

### 8.3 Persistent Agent-local State

Core 不强制规定完整的“人类 Memory 模型”。Core 真正保证的是：

> Agent 可以拥有跨 Wake 持续存在、Timeline-local、私有且可按预算检索进入 Context 的内部状态。

`episodic memory / semantic memory / consolidation / decay / trauma / human emotion` 等具体认知语义属于 Capability。

### 8.4 Decision

Core 定义 Agent 的认知边界与 Decision/Intent 协议，但不定义 Agent **为什么** 行动。

Goal、Need、Policy、Role Duty、Habit、Emotion、External Command 等都可以由 Capability 作为 Decision Driver / Bias 提供。

因此 Goal、Plan、Personality、Emotion 不是 Kernel 强制字段。

> **Core defines how an Agent can decide; Capability defines why and with what semantics.**

LLM 只是 Cognitive Path 中一种昂贵的认知执行器，不是 Agent 本身，也不是 Runtime 本身。

## 9. Runtime

Loom Runtime 是 **event-driven + demand-driven + world-time-aware** 的世界执行器，不通过固定 Tick 扫描整个世界。

```text
Pending Work
    ↓
Runtime Router
    ├── Fast Path
    └── Cognitive Path
            ↓
          Intent
            ↓
          Resolve
            ↓
          Evaluate
            ↓
          Commit
            ↓
          Event
            ↓
          State
            ↓
Reaction / Perception / Scheduler
            ↓
         New Work
```

### 9.1 Fast Path

机械性、确定性、规则化工作默认走 Fast Path，不需要 Agent 或 LLM。

例如：期限到期、状态过期、确定性结算、自动流程推进等。

### 9.2 Cognitive Path

只有当工作确实需要主体自主认知时，才进入 Agent Wake / Context / Decision。

Stimulus 不等于模型调用。Runtime 先执行 routing、relevance、activation、budget 判断，再决定是否调用昂贵 Cognition。

> **Agent persists; compute is on demand.**

### 9.3 Work Queue

Scheduler、Reaction、External Input、Application Intervention、Process Continuation、Agent Deferred Work 等统一进入 Runtime Work Queue。

Work Item 只是“需要处理的工作”，不等于 Stimulus、Intent 或 Event；Work 最终可以被忽略而不产生世界变化。

### 9.4 Commit Authority

Timeline Commit 是世界状态变化的唯一线性化点。

Resolution 可以并行，但 Commit 必须依据最新 Timeline State 保证一致性。并发冲突需要失败、重试或重新 Resolve，不能产生互相矛盾的双重成功。

Reaction 不允许递归直接修改世界，应产生新的 Work Item 回到 Queue，并受到 reaction depth / work / compute 等预算限制。

### 9.5 Resumability

持续 World 不等于永久 `while(true)` 进程。

World 的 State、Timeline、Future Work 与 Scheduler 持久存在；Runtime Compute 可以停止并在之后重新加载继续推进。

> **World persists; runtime execution is resumable.**

## 10. Rule / Validation Kernel

Core 不把所有规则视为“违反即拒绝”。至少区分：

- Runtime Invariant；
- Feasibility / structural constraint；
- Access / Authority / Permission；
- Law / Policy / Norm；
- Enforcement / Reaction。

只有少量 Runtime Invariant 必须阻止 Commit，例如身份一致性、Timeline isolation、Event sequencing、State schema integrity、atomicity、referential integrity 等。

违法、违规、失礼或违反制度通常仍然可以成为真实 Event；规则存在不等于遵守、发现、判断、执行或同等后果。

Core Rule Kernel 只提供 applicability / evaluation / invariant validation / reaction registration 等协议，不理解具体法律、制度、社会规范或游戏规则。

Actual Rule 与 Agent Belief About Rule 必须分离。

## 11. Capability Host

Extensibility 本身属于 Core，但具体 Capability 不属于 Core。

Capability Host 的最小职责：

```text
Discover
Validate
Bind
Invoke
Version / identify implementation
```

Capability Module 可以向 Core 贡献：

- State Facet Definitions；
- Relationship Definitions；
- Action Definitions；
- Resolvers；
- Rule / Evaluator Definitions；
- Runtime Handlers；
- migrations / projections / domain contracts as needed。

Capability 定义语义，Core 拥有运行数据和生命周期。

Capability **不得**：

- 直接修改 Timeline State；
- 直接写 Event Ledger；
- 修改稳定 Entity/Relationship Identity；
- 依赖 Core 内部数据库表结构；
- 启动自己的 World 主循环；
- 绕过 Scheduler / Runtime Queue；
- 直接决定 LLM Wake；
- 把 Agent 不可见的 World Truth 偷渡进 Agent Context。

多个 Capability 若确实需要稳定协作，应通过 Core-owned contract / Event / Action / Relationship / Work 等协议，而不是互相调用内部实现。

## 12. Core Admission Rule

未来任何新概念想进入 Core，都必须通过以下测试：

### Test A — Closure

拿掉它以后，一个持续 World Runtime 是否仍能完整运行？

如果能，优先放 Capability。

### Test B — Mechanism vs Semantics

它描述的是：

- **世界如何存在/运行** → Core candidate；
- **某种世界里有什么/意味着什么** → Capability candidate。

### Test C — World Substitution

将现代人类社会替换为：

- 中世纪魔法世界；
- 机器文明；
- RPG；
- 纯机械市场；
- 舆情/信息传播世界。

如果概念仍然是 Runtime 闭环所必需，它才更像 Core。

## 13. Core MUST NOT know

Core 不应天然理解以下具体领域概念：

```text
人类心理学中的具体情绪
人生需求与价值观
工资 / 职业 / 劳动合同
婚姻 / 家庭制度
货币 / 股票 / 银行账户
政府制度 / 具体法律
新闻 / 财报 / 舆情语义
战斗 / HP / 魔法 / 任务
驾驶 / 医疗 / 教育
```

同样，`Observation / Information Artifact / Claim / Institution / Goal / Plan / Human Memory / Emotion` 等此前讨论过且非常重要的高级概念，除非其最低层机制通过上述 Core Admission Rule，否则应作为官方 Foundational Capability 或 Domain Capability 提供，而不是自动进入 Kernel。

它们的设计语义仍然有效；本原则只重新确定其架构归属。

## 14. Core Closure Statement

Loom Core 的最小闭包可以概括为：

> **Core 能够让一个有稳定身份和 Timeline-local State 的世界，在 World Time 中通过统一 Runtime 处理工作；需要自主认知时，Agent 基于受隔离且有预算的局部 Context 产生 Intent；所有实际变化都经过 Resolve / Evaluate / Commit 成为不可变 Event，并形成新的 State 与后续 Work；同时 Capability Host 可以为这些机制赋予任意领域语义，而不能夺取 Runtime 权威。**

这套闭包必须能够同时承载人生模拟、RPG、舆情/信息世界、现实镜像以及没有 Agent 的机械世界，而无需向 Core 注入相应领域知识。