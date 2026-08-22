# Loom：持续演化智能世界引擎

> **Loom lets you create worlds that keep living.**

Loom 是一个用于构建、运行和扩展**持续演化智能世界**的开放引擎。

它的核心不是执行一次模拟、生成一份报告，或让一组 Agent 对话若干轮，而是维护一个能够长期存在的 **World**：世界拥有自己的身份、长期运行语义契约、历史、当前状态、时间和未来待处理事项；它可以被暂停、恢复、观察、干预、分叉，并继续沿自己的因果历史演化。

## 1. Loom 运行的是 World

```text
Create / Load World
        ↓
    Loom Runtime
        ↓
Continuous Evolution
```

World 不是 API 请求、simulation job 或 Application session。报告、预测、故事、游戏画面和分析结果都只是对 World 的观察或使用方式，不是 World 生命周期的终点。

世界中的**语义状态变化**统一形成历史：

```text
Input / Stimulus / Intent
          ↓
        Runtime
          ↓
        Resolve
          ↓
         Event
          ↓
        Effect
          ↓
Materialized World State
```

> **No semantic World State mutation without a committed Event.**

Entity、Relationship、Facet 等世界语义状态不能被直接修改；任何这类真实变化都必须先成为该 Timeline 上的 committed history，并由 Event 的 frozen Effects 解释。

但 Loom 还存在另一类不会伪装成领域 Event 的可重建 Timeline 状态，例如：

```text
World Time
logical Durable Work lifecycle
Timeline logical revision / ancestry
```

它们遵守另一条规则：

> **No Timeline logical-state mutation without a Runtime-owned logical commit.**

lease、fence、retry backoff 等平台可靠性数据则继续留在独立 Operational State 中。

## 2. 五层架构

Loom 使用五个清晰的所有权边界：

```text
                 Loom Core
                    ↓
           Capability Modules
                    ↓
             World Template
                    ↓
                  World
                    ↑
                    │
               Application
```

- **Core**：定义世界怎样存在和运行。
- **Capability Module**：定义世界会什么、具体语义意味着什么。
- **World Template**：组合 Capability requirements、初始规则、World Time 和默认配置，是创建 World 的“出生配方”。
- **World**：真正持续存在并拥有历史与长期 Runtime Binding 的运行实例。
- **Application**：用户如何创建、观察、分析、交互、干预或控制 World 运行节奏的产品体验。

> **Core decides how worlds exist and run; Capability defines semantics; Application defines purpose and experience.**

一个 Application 可以管理多个 World；同一个 World 也可以被不同 Application 以不同方式观察和使用。

### World Runtime Binding 不是第六层

一个已经出生的 World 持有自己的 **World Runtime Binding**：

```text
which Capability semantic domains are enabled
compatible Capability requirements
immutable assembly configuration where genuinely required
Template/birth provenance
```

它属于 World-level runtime metadata，不是新的产品层。

必须区分：

```text
Installed Capability
= 当前平台有这个实现

Enabled Capability
= 这个 World 的 Binding 允许这个 semantic domain
```

Runtime 中安装一个 Capability，并不自动让所有 World 都拥有它。

## 3. Core 只保留世界运行所必需的机制

Loom Core 是 **world runtime**，不是某个领域模拟器。

Core 的概念闭包由以下职责组成：

```text
World & Timeline
Identity & Structure
State
History
Time
Agency
Runtime
Capability Host
```

其中既包含世界原语，也包含 Runtime 必需的设施和协议，例如 World Runtime Binding mechanism、Timeline Logical Commit、Durable Work、Scheduler、Ingress、Feedback、Cognitive Execution、Execution Provenance 等。

Core 不理解“人、公司、国家、工资、婚姻、股票、新闻、魔法、战斗、恐惧”等具体领域语义。它只提供足够稳定、通用的机制，让 Capability 能够表达这些世界。

## 4. 世界只有一条权威历史，主体拥有自己的轨迹

一个 World 可以拥有多条 Timeline，用于主历史、预测、实验或反事实分支。

```text
World
├── Runtime Binding       # all Timelines share it
├── Main Timeline
├── Scenario Timeline
└── Counterfactual Timeline
```

每条 Timeline 只有一份权威 Event Ledger，并拥有自己的 World Time 和 logical Future。

个人、公司、国家等 Entity 不各自拥有独立权威 Timeline；它们在某条 World Timeline 上拥有自己的 **Trajectory**。同一个 Event 可以同时进入多个 Entity 或 Relationship 的 Trajectory，因此不同主体的发展路径会相交、碰撞并产生新的因果结果。

> **Timeline is the history of the world; Trajectory is the history of an identity within that world.**

Identity 属于 World；可变 semantic State 属于 Timeline。Fork 创建的是同一批既有身份的另一段历史，而不是把“张三”复制成另一个身份。

Fork 同时继承 fork point 的 World Time 与 logical Pending Work，但后续 State、World Time、Work lifecycle 和未来结果各自独立；World Runtime Binding 因属于 World 而保持相同。

## 5. Agent 是世界中的持续存在者，LLM 只是可配置认知执行器

Loom 支持 Agent，但不是所有 World 都必须拥有 Agent。

Agent 是具有局部认知边界和自主决策能力的 Actor。它只能依据自己可获得的局部世界表示和 Context 行动，而不能默认读取全知 World State。

```text
World Truth
    ↓
Perception / Access Boundary
    ↓
Agent-local Representation
    ↓
Context
    ↓
Decision / Intent
```

LLM 不等于 Agent，也不等于 Runtime。Core 提供可配置的 **Cognitive Execution** 能力，具体执行器可以是 LLM、规则、策略、行为树、小模型、人类或混合实现。

v0 标准 cognition path 是：

```text
AgentWorldView
    ↓
Cognitive Executor
    ↓
Decision::Act(ActionInvocation) / NoAction
    ↓
normal Runtime + Capability authority
```

Cognitive Executor 不能直接输出 Event、Effect、Resolution 或 World-Time control authority。

Core 不规定固定的 `Fast Path → Cognitive Path` 流水线。Runtime 通过可替换的 Execution Policy / Strategy 决定一次工作采用确定性逻辑、策略、认知执行或组合方式。

> **Agent persists; compute is on demand.**

## 6. 过去、现在、时间和未来被明确分离

一条 Timeline 的运行结构可以概括为：

```text
Event Ledger        = 已经确定的语义过去
Materialized State  = 当前语义现实
World Time          = 当前 Timeline 语义时间坐标
Durable Work        = 尚未确定结果的未来执行义务
```

Scheduled future 不是 future fact。未来 Work 真正执行时，需要根据当时最新的 Timeline State 判断结果。

### World Time 不由 Event 推动

World Time 是显式、单调、可重建的 Timeline Logical State。

禁止把它定义成：

```text
max(Event.occurred_at)
PlatformClock.now()
database NOW()
worker sleep duration
```

真正的推进必须经过 Runtime authority 的显式 logical transition：

```text
AdvanceWorldTime(T_current -> T_next)
```

它不需要伪造领域 Event，但必须持久化、参与 TimelineVersion/CAS，并能被 Replay/Fork 精确恢复。

因此 Runtime 才能真正闭环：当没有当前 due Work、但存在未来 Work 时，time policy 可以显式推进到合适的 WorldInstant，再恢复执行。

## 7. Runtime 安装能力，World 决定启用能力，Session 决定实际软件

Loom 必须区分三个不同层次：

```text
Installed Capability Implementations
        ↓ software availability
World Runtime Binding
        ↓ semantic enablement / compatibility
Execution Session / Assembly
        ↓ exact implementation used now
```

每个可能形成 World Truth 的 root execution 都建立一个 Execution Session。

Session 开始时 Runtime pin：

```text
target World / Timeline
TimelineVersion
World Runtime Binding
active Runtime Revision
exact compatible Capability implementations
execution policy
controlled entropy/cognition environment where relevant
```

同一个 Session 及其 subresolution 不能中途切换 Runtime Revision 或 exact implementation。

如果当前 Runtime Revision 无法满足目标 World 的 Binding，执行应失败为 unavailable/incompatible；Runtime 不得静默修改 World Binding 或启用其他 semantic domain。

## 8. 世界可以连接现实，但 Core 不直接控制现实

外部系统通过 **Ingress Protocol** 向 Loom 提交输入；输入不会直接修改 State，而是进入 Runtime 并经过领域解释、Resolution 和 Event Commit。

Ingress 的 source/platform timestamp 也不会自动推动 World Time。如果一个 Reality Mirror Application 希望把现实时间映射到 World Time，应由明确 policy 请求 Runtime 的 World-Time transition。

Loom 通过 **World Change Feed / Feedback** 把已经提交的世界变化提供给 Application 或外部观察者。

```text
                  External
               ↙            ↖
            Ingress       Feedback
               ↓             ↑
             Runtime → Event ┘
```

Feedback 是只读观察边界。Loom Core 不直接执行现实世界副作用；如果外部 Application 根据反馈决定再次影响 World，应重新通过 Ingress 进入 Runtime。

## 9. 世界演化，软件升级

> **Worlds evolve; software upgrades. Never confuse the two.**
>
> **世界只会演化，软件才会升级。**

法律、制度、技术、领域能力和社会规则的变化属于 World 自己的历史，只影响其有效 World Time 之后的世界行为，不重写过去。

World Runtime Binding 是该 World 长期的 semantic software contract，但它不永久 pin exact binary。

Core 或 Capability implementation 的 Bug 修复和软件发布属于平台历史。新的 Runtime Revision 激活以后，新启动的 Execution Session 使用当前且满足 World Binding 的 compatible implementation；已经提交的 Event 不重新计算，已经开始的一次 Execution Session 不在中途切换实现。

平台变化通过独立的 Runtime Change Ledger 和 Execution Provenance 被人类审计，但默认不进入 Agent Context，也不是 World Event。

## 10. Replay 与 Fork 不重新运行历史软件

Historical Replay 的 authority 是：

```text
Committed Events + frozen Effects
→ reconstruct semantic materialized State

Timeline Logical History
→ reconstruct World Time + logical Durable Work
```

Replay 不重新调用旧 Resolver、Entropy、Cognitive Executor，也不依赖旧 binary 才能知道“当时世界发生了什么”。

Execution Provenance 保存的是“当时是怎么计算出来的”，不是 replay authority。

Counterfactual re-simulation 则从一个历史 TimelineVersion Fork，使用新的 Execution Session 计算另一种未来，因此可以自然使用当前 compatible software。

## 11. Loom 的用途由上层决定

同一个 Core 可以承载完全不同的世界：

```text
Life Simulation
RPG / Strategy Game
Public Opinion Analysis
Prediction / Scenario Analysis
Social Experiment
Decision Sandbox
Reality Mirror
Mechanical Market Simulation
```

这些用途的差异应该主要来自 Capability、Template、World Runtime Binding 和 Application，而不是通过修改 Core 把 Loom 固化成某一种产品。

## 12. 设计方向

Loom 的核心目标不是让每个世界都拥有相同内容，而是提供一组足够小、足够稳定、足够可组合的运行机制，使不同世界能够长期存在并自然产生不同历史。

因此后续设计遵循一个严格准入标准：

> **如果移除一个概念后，持续 World Runtime 仍然能够闭环，那么它原则上不应进入最小 Core。**

同时遵循三个 authority test：

```text
semantic World State change
→ committed Event + frozen Effect

reconstructable Timeline time/future change
→ Runtime-owned Logical Commit

platform reliability bookkeeping
→ Operational State only
```

Core 保持稳定；新的世界能力优先通过 Capability 扩展。详细闭环见 `docs/architecture/world-runtime.md`。