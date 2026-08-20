# Loom Five-Layer Architecture

> Status: confirmed top-level ownership boundary.

本文只回答一个问题：**一个概念应该属于哪一层？**

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

这不是部署分层，也不是 Rust `Cargo.toml` 依赖图，而是**架构/语义所有权边界**。

Rust 物理依赖必须单独遵守 `docs/architecture/governance.md` 中的 `Kernel → Protocol → Contracts → Runtime → Adapters → Applications` dependency architecture。尤其不能把上图中的调用/拥有关系直接翻译成 crate dependency。

> **Semantic ownership, runtime call flow and Cargo dependency direction are different graphs.**

## 1. Core

**Core 定义一个持续 World 怎样存在和运行。**

Core 只保留跨领域、闭环必需的 world primitives 与 runtime facilities：World/Timeline、Identity、State、Event/Effect、Time、Agency、Runtime、Capability Host，以及 Durable Work、Ingress、Feedback、Cognitive Execution、Execution Provenance 等必要协议。

Core 不理解具体领域语义，例如人、公司、国家、工资、婚姻、股票、新闻、战斗、魔法、恐惧等。

具体 Core 闭包以 `docs/architecture/core.md` 为唯一详细定义。

## 2. Capability Module

**Capability Module 为 Core 提供可复用的世界/领域语义。**

Capability 可以定义：

- State Facet schema 与语义；
- Relationship semantics；
- Action Definitions；
- Resolvers；
- Rule / Evaluator；
- domain handlers / projections；
- cognition/decision semantics；
- information、institution、memory、goal 等可复用基础能力；
- employment、economy、combat、health、politics 等领域能力。

Capability 定义 meaning，Core 保留 runtime authority。

Capability 不能直接修改 Timeline State、写 Event Ledger、绕过 Commit、越过 Agent knowledge boundary 或隐藏影响 World Truth 的外部不确定性。

Capability 同样不能自行决定 Loom 如何对外暴露这些语义：HTTP、CLI、GPUI、SDK 等公共入口统一由 `loom-api` 管理。具体强制规则见 `docs/architecture/governance.md`。

### Foundational 与 Domain 只是分类

Capability 可以按复用范围分为：

```text
Foundational Capability
- information
- institution
- memory
- goal / planning
- generic social / resource

Domain Capability
- employment
- finance
- health
- combat
- magic
- politics
```

这不是新的架构层级，两者都仍是 Capability Module。

## 3. World Template

**World Template 是创建某一类 World 的出生配方。**

它组合：

```text
Capability selection
initial rules
initial defaults
initial configuration
initial world data/profile
```

例如：

```text
modern-human-life
modern-society
real-world-mirror
medieval-fantasy
corporate-simulation
```

Template 不运行世界，也不持续控制已经创建的 World。

Template 后来变化，只影响之后创建的 World；已有 World 继续沿自己的 Timeline、State、Rules 和 Events 演化。

> **Template is a birth recipe, not a subscription.**

## 4. World

**World 是实际被创建、持续存在并拥有历史的运行实例。**

一个 World 拥有稳定身份，并包含/关联：

```text
Timelines
World Entity identities
Timeline-local State
Relationships
Event history
Durable Work / runtime state
world rules and capability semantics in effect
```

World 不是请求、报告、一次模拟任务或 Application session。

一个 World 可以拥有多个 Timeline，但每条 Timeline 只有一份权威 Event Ledger。

法律、制度、技术、社会能力等变化属于 World 自己的历史演化，而不是“升级 World package”。

## 5. Application

**Application 是用户拿 Loom 来做什么以及如何体验 World。**

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
- 观察或管理一个/多个 World；
- 读取 World Change Feed；
- 提供 UI、叙事、分析和报告；
- 通过 Loom API / Ingress 向 World 提交用户输入或干预；
- Fork Timeline 用于实验、预测或反事实分析。

Application 不拥有直接 State mutation 权限，也不因为产品体验不同而重定义 Core semantics。

同一个 World 可以被多个 Application 以不同方式观察和使用；这些 Application 的 Engine 能力入口统一通过 `loom-api`，不直接 import 领域 Capability 或 Storage repository 作为产品功能接口。

## 6. Ownership Test

新增概念时依次判断：

1. **没有它，跨领域的持续 World Runtime 是否无法闭环？** 是 → Core candidate，继续通过 Core Admission Review。
2. **它是否定义一种可复用的世界语义/能力？** 是 → Capability Module。
3. **它是否只是用于创建 World 的能力组合和初始配置？** 是 → World Template。
4. **它是否是某个已经创建的世界自己的身份、状态、规则或历史？** 是 → World / Timeline。
5. **它是否定义用户目的、展示、分析或交互方式？** 是 → Application。

若一个需求横跨多层，应拆分责任，而不是把边界合并。

这个 Ownership Test 只判断**概念归属**；决定 Rust 类型放在哪个 crate、谁可以依赖谁时，还必须通过 `governance.md` 的 dependency/type-placement rules。

## 7. Stable Boundary

Loom 当前稳定的顶层模型：

> **Core -> Capability Module -> World Template -> World <- Application**

可进一步概括为：

```text
Core        → Mechanism
Capability  → Semantics
Template    → Initial Composition
World       → Living Instance / Reality
Application → Purpose / Experience
```

Rust 实现层的稳定原则另行概括为：

```text
Core      = World Language
Protocol  = Internal Execution Language
API       = Public Consumption Language
Runtime   = Execution Authority
Adapters  = concrete infrastructure / extension implementations
Apps      = composition roots and consumers
```
