# Loom：持续演化智能世界引擎

> **Loom lets you create worlds that keep living.**

Loom 是一个用于构建、运行和扩展**持续演化智能世界**的开放引擎。

它的核心不是执行一次模拟、生成一份报告，或让一组 Agent 对话若干轮，而是维护一个能够长期存在的 **World**：世界拥有自己的身份、历史、当前状态、时间和未来待处理事项；它可以被暂停、恢复、观察、干预、分叉，并继续沿自己的因果历史演化。

## 1. Loom 运行的是 World

```text
Create / Load World
        ↓
    Loom Runtime
        ↓
Continuous Evolution
```

World 不是 API 请求、simulation job 或 Application session。报告、预测、故事、游戏画面和分析结果都只是对 World 的观察或使用方式，不是 World 生命周期的终点。

世界中的真实变化统一形成历史：

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
         State
```

> **No mutation without a committed Event.**
>
> 世界状态不能被直接修改；任何真实变化都必须先成为该 Timeline 上的历史。

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
- **World Template**：组合 Capability、初始规则和默认配置，是创建 World 的“出生配方”。
- **World**：真正持续存在并拥有历史的运行实例。
- **Application**：用户如何创建、观察、分析、交互或干预 World 的产品体验。

> **Core decides how worlds exist and run; Capability defines semantics; Application defines purpose and experience.**

一个 Application 可以管理多个 World；同一个 World 也可以被不同 Application 以不同方式观察和使用。

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

其中既包含世界原语，也包含 Runtime 必需的设施和协议，例如 Durable Work、Scheduler、Ingress、Feedback、Cognitive Execution、Execution Provenance 等。

Core 不理解“人、公司、国家、工资、婚姻、股票、新闻、魔法、战斗、恐惧”等具体领域语义。它只提供足够稳定、通用的机制，让 Capability 能够表达这些世界。

## 4. 世界只有一条权威历史，主体拥有自己的轨迹

一个 World 可以拥有多条 Timeline，用于主历史、预测、实验或反事实分支。

```text
World
├── Main Timeline
├── Scenario Timeline
└── Counterfactual Timeline
```

每条 Timeline 只有一份权威 Event Ledger。

个人、公司、国家等 Entity 不各自拥有独立权威 Timeline；它们在某条 World Timeline 上拥有自己的 **Trajectory**。同一个 Event 可以同时进入多个 Entity 或 Relationship 的 Trajectory，因此不同主体的发展路径会相交、碰撞并产生新的因果结果。

> **Timeline is the history of the world; Trajectory is the history of an identity within that world.**

Identity 属于 World；可变 State 属于 Timeline。Fork 创建的是同一批既有身份的另一段历史，而不是把“张三”复制成另一个身份。

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

Core 不规定固定的 `Fast Path → Cognitive Path` 流水线。Runtime 通过可替换的 Execution Policy / Strategy 决定一次工作采用确定性逻辑、策略、认知执行或组合方式。

> **Agent persists; compute is on demand.**

## 6. 过去、现在和未来被明确分离

一条 Timeline 的运行结构可以概括为：

```text
Event Ledger   = 已经确定的过去
State          = 当前现实
Durable Work   = 尚未确定结果的未来执行义务
```

Scheduled future 不是 future fact。未来 Work 真正执行时，需要根据当时最新的 Timeline State 重新判断结果。

Fork 共享 Fork Point 之前的历史祖先，并继承当时的逻辑 State 与待处理 Work；Fork 之后的 State、Work 和未来结果各自独立演化。

## 7. 世界可以连接现实，但 Core 不直接控制现实

外部系统通过 **Ingress Protocol** 向 Loom 提交输入；输入不会直接修改 State，而是进入 Runtime 并经过领域解释、Resolution 和 Event Commit。

Loom 通过 **World Change Feed / Feedback** 把已经提交的世界变化提供给 Application 或外部观察者。

```text
                  External
               ↙            ↖
            Ingress       Feedback
               ↓             ↑
             Runtime → Event ┘
```

Feedback 是只读观察边界。Loom Core 不直接执行现实世界副作用；如果外部 Application 根据反馈决定再次影响 World，应重新通过 Ingress 进入 Runtime。

## 8. 世界演化，软件升级

> **Worlds evolve; software upgrades. Never confuse the two.**
>
> **世界只会演化，软件才会升级。**

法律、制度、技术、能力和社会规则的变化属于 World 自己的历史，只影响其有效时间之后的世界行为，不重写过去。

Core 或 Capability 实现的 Bug 修复和软件发布属于平台历史。新的 Runtime Revision 激活以后，新启动的 Execution Session 使用当前实现；已经提交的 Event 不重新计算，已经开始的一次 Execution Session 不在中途切换实现。

平台变化通过独立的 Runtime Change Ledger 和 Execution Provenance 被人类审计，但默认不进入 Agent Context，也不是 World Event。

## 9. Loom 的用途由上层决定

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

这些用途的差异应该主要来自 Capability、Template 和 Application，而不是通过修改 Core 把 Loom 固化成某一种产品。

## 10. 设计方向

Loom 的核心目标不是让每个世界都拥有相同内容，而是提供一组足够小、足够稳定、足够可组合的运行机制，使不同世界能够长期存在并自然产生不同历史。

因此后续设计遵循一个严格准入标准：

> **如果移除一个概念后，持续 World Runtime 仍然能够闭环，那么它原则上不应进入最小 Core。**

Core 保持稳定；新的世界能力优先通过 Capability 扩展。