# Loom Five-Layer Architecture

> Status: confirmed top-level architecture boundary.
>
> 本文定义 Loom 的五层责任边界。新增任何概念时，第一问应当是：**它属于哪一层？**

## 1. Overview

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

这不是部署分层，而是架构所有权边界。

- **Core**：定义一个持续智能世界如何存在和运行。
- **Capability Module**：为 Core 提供可复用的领域/世界语义能力。
- **World Template**：组合 Capability、初始规则和默认配置，形成可复用的“出生配方”。
- **World**：被真正创建、持续存在并拥有历史的运行实例。
- **Application**：用户如何创建、观察、分析、交互或干预 World 的产品体验。

> **Core -> Capability Module -> World Template -> World <- Application**

## 2. Core

### Definition

**Loom Core is the domain-neutral world kernel and runtime.**

Core 的最小职责已经收敛为八个 Kernel Concern：

```text
1. World & Timeline
2. Identity & Structure
3. State
4. History
5. Time
6. Agency
7. Runtime
8. Capability Host
```

更具体的 Core 闭包定义见 `docs/architecture/core.md`。

Core 负责：

- World / Timeline 的身份、生命周期和 Fork；
- Entity / Actor / Agent / Relationship 的稳定结构身份；
- Timeline-local State 与 State Facet 生命周期；
- Event Ledger、Effect、因果和唯一 Commit Authority；
- WorldClock / Scheduler；
- Agent-local view、有限 Context、Decision / Intent 协议；
- event-driven / demand-driven Runtime Queue、Resolve、Evaluate、Commit、Reaction；
- Capability 的注册、绑定和受控调用。

Core **不**天然理解：

```text
human
company
country
salary
job
marriage
stock
bank account
news
public opinion
fear
guilt
combat
HP
magic
quest
```

Core 只提供机制，不提供这些领域语义。

此前讨论过的 `Observation / Information Artifact / Claim / Institution / Goal / Plan / Human Memory / Emotion` 等高级概念仍然是 Loom 重要能力，但其架构归属必须通过 Core Admission Rule 判断；默认不因为“重要”就进入 Kernel。

## 3. Capability Module

### Definition

**Capability Module 为 Core 原语赋予一种可复用的世界语义或能力。**

它不是完整产品，也不拥有 World 生命周期和 Commit Authority。

Capability 可以是基础型的：

```text
information
institution
goal
planning
social
resource
memory
```

也可以是领域型的：

```text
employment
family
economy
finance
health
politics
combat
inventory
magic
mobility
```

这两类架构地位相同，只是复用范围不同。

Capability 可以贡献：

- State Facet Definitions；
- Relationship Definitions；
- Action Definitions；
- Resolvers；
- Rule / Evaluator Definitions；
- Runtime Handlers；
- projections / migrations / domain contracts as needed。

Capability 定义语义，Core 管理运行数据、Timeline、Event、State、Scheduler 和 Commit 生命周期。

Capability 不得直接写 State/Ledger、启动自己的 World 主循环、绕过 Scheduler/Runtime、直接唤醒 LLM 或突破 Agent 的认知边界。

### Composition

多个 Capability 可以在同一 World 中组合，但不应互相调用内部实现形成耦合网。

当确实需要协作时，应通过 Core-owned contract、Event、Action、Relationship、Work 或其他稳定协议完成。

## 4. World Template

### Definition

**World Template 是创建某类 World 的可复用出生配方。**

例如：

```text
modern-human-life
modern-society
real-world-mirror
corporate-society
medieval-fantasy
```

Template 可以组合：

```text
Capability selection
initial rules
initial state/schema defaults
initial configuration
world bootstrap data
```

但 Template 不是运行中的 World，也不是持续控制 World 的订阅关系。

> **Template creates a World; it does not keep governing it.**

Template 后续变化只影响未来新建 World，除非某个已存在 World 自己通过历史事件发生相应变化。

## 5. World

### Definition

**World 是实际被创建并持续存在的世界实例。**

World 拥有稳定身份，并包含或引用：

```text
World identity
World Entities / Relationships
Timelines
Timeline-local State
Event history
Future scheduled work
World rules / semantic state
Capability semantic bindings needed by that World
```

World 不是 API 请求、simulation job、report 或 Application session。

### Timeline

一个 World 可以有多条 Timeline：

```text
World
├── Main Timeline
├── Scenario Timeline
└── Counterfactual Timeline
```

每条 Timeline 是一条独立的权威历史分支，并拥有唯一权威 Event Ledger。

个人、公司、国家等主体不各自拥有独立 Timeline；它们在某条 World Timeline 上拥有自己的 **Trajectory**。

### Identity

> **Identity belongs to World; mutable State belongs to Timeline.**

同一 World Entity 在不同 Timeline 上仍然是同一个 Identity，只是关系、经历、状态、认知和后续轨迹可以不同。

名字不是 Identity；稳定内部 ID 才是权威身份标识。

## 6. Application

### Definition

**Application 是基于 Loom 构建的上层产品。**

例如：

```text
Life Simulator
RPG / Strategy Game
Public Opinion Analysis
Prediction / Scenario Analysis
Social Experiment Platform
Decision Sandbox
Reality Mirror Dashboard
```

Application 可以：

- 从 Template 创建 World；
- 选择/配置 Capability；
- 与已有 World 交互；
- 观察一条或多条 Timeline；
- 展示叙事、可视化和分析投影；
- 发起受 Runtime 管理的用户干预；
- 创建 Scenario / Counterfactual Fork。

Application 不拥有 World Truth，也不能直接修改 Timeline State 或绕过 Event Ledger。

> **Application is not World.**

同一个 World 可以被多个不同 Application 观察和使用，而无需复制底层世界。

## 7. Examples

### Life Simulation

```text
Application:
Life Simulator

World Template:
modern-human-life

Capabilities:
human cognition / social / family / employment / economy / health / information ...

Core:
standard Loom world kernel
```

### RPG

```text
Application:
RPG Game

World Template:
medieval-fantasy

Capabilities:
character / inventory / combat / quest / economy / magic ...

Core:
standard Loom world kernel
```

### Public Opinion Analysis

```text
Application:
Public Opinion Analysis

World Template:
modern-society / real-world-mirror

Capabilities:
information / media / institution / social propagation / source ingestion / analysis ...

Core:
standard Loom world kernel
```

### Mechanical Market

```text
Application:
Market Simulation / Exchange Testbed

World Template:
mechanical-market

Capabilities:
asset / order / matching / market rules

Agents:
optional or zero

Core:
standard Loom world kernel
```

四种用途不同，但不要求向 Core 注入对应领域知识。

## 8. Ownership Test

新增概念时按以下顺序判断：

1. **如果移除它，持续 World Runtime 是否无法闭环？**
   - 是：可能属于 Core。
   - 否：优先考虑 Capability。
2. **它描述的是机制还是语义？**
   - “世界如何存在/运行” → Core candidate。
   - “某种世界里有什么/意味着什么” → Capability candidate。
3. **它是否只是创建时的组合与默认值？**
   - 是 → World Template。
4. **它是否是一个具体已创建世界的事实、状态或历史？**
   - 是 → World / Timeline。
5. **它是否定义用户拿 Loom 做什么以及如何体验？**
   - 是 → Application。

如果一个概念看起来跨层，应拆分责任，而不是打破边界。

## 9. Evolution Boundary

Loom 必须严格区分：

```text
World evolution
Software upgrade
Historical alternative
```

- World 通过自己的 Event / Rule / State 演化；
- Core / Capability implementation 可以升级，但技术升级默认不改变 World Truth；
- 若要改变过去的因果结果，应通过 Fork / Replay 创建另一条 Timeline，而不是重写历史。

Template 是出生配方，不持续同步已创建 World。

详细约束见 `docs/architecture/evolution.md`。

## 10. Stable Boundary

以下边界已经作为 Loom 架构基线确认：

> **Core owns existence, identity, time, history, state transition, cognition boundaries and orchestration. Capability owns semantics. Application owns purpose and experience.**

未来设计应保持：

> **Core -> Capability Module -> World Template -> World <- Application**

除非后续明确的架构决策正式替代本基线。