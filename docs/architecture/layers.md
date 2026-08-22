# Loom Five-Layer Architecture

> Status: confirmed top-level ownership boundary after World Runtime Closure review.

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

另一个同样重要的澄清：**World Runtime Binding 不是第六个架构层。** 它是已经出生的 World 自己持有的持久执行契约；Template 在出生时生成它，Runtime 在执行时强制它。详细语义见 `world-runtime.md`。

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

### 2.1 Installed implementation is not World enablement

Capability implementation 被安装/注册到某个 Runtime Revision，只代表平台“有能力运行它”，不代表所有 World 自动启用它。

```text
Installed Capability
= platform/software availability

Enabled Capability
= World Runtime Binding permits that semantic domain
```

Runtime 必须在目标 World 的 Binding 范围内 dispatch Action、Work、Reaction、subresolution 和其他 semantic execution。

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
Capability requirements / selection
immutable assembly configuration where required
initial rules / defaults
initial World Time
ordered bootstrap recipe / initial world data profile
```

例如：

```text
modern-human-life
modern-society
real-world-mirror
medieval-fantasy
corporate-simulation
```

Template 经过 Runtime validation/assembly 后，产生一个 World birth plan，包括初始 World Runtime Binding 和 bootstrap execution recipe。

Template 不运行世界，也不持续控制已经创建的 World。

Template 后来变化，只影响之后创建的 World；已有 World 继续沿自己的 Timeline、State、Rules、World Time 和 Events 演化。

> **Template is a birth recipe, not a subscription.**

### 3.1 Template does not permanently pin code

Template 可以声明 Capability compatibility requirement，但“出生时解析到 implementation 1.2.3”不等于 World 永久运行该 binary。

出生时 exact implementation/version 属于 bootstrap Execution Session provenance；World 自己保留的是 semantic requirement / binding。

这样同时满足：

```text
Template determines birth semantics
World keeps its semantic capability contract
future Execution Sessions use current compatible software
past Events keep exact implementation provenance
```

## 4. World

**World 是实际被创建、持续存在并拥有历史的运行实例。**

一个 World 拥有稳定身份，并包含/关联：

```text
World Runtime Binding
Template/birth provenance
Timelines
World Entity identities
Timeline-local materialized State
Timeline-local World Time
Relationships
Event history
Durable Work / logical future state
```

World 不是请求、报告、一次模拟任务或 Application session。

### 4.1 World Runtime Binding belongs to World

World Runtime Binding 是 World-level runtime metadata，不是新的架构层。

它回答：

```text
which Capability semantic domains are enabled
which compatibility requirements/configuration apply
which Template/revision produced this birth contract
```

它不回答：

```text
which exact Runtime Revision must run forever
which exact Capability binary must run forever
which worker/process currently owns execution
```

Exact software implementation binding 属于每次 Execution Session。

World 的所有 Timeline 默认共享同一 Binding；Fork 不创建另一套 semantic assembly。

### 4.2 World contains several different state domains

不能再把所有持久数据笼统称为“World State”。至少区分：

```text
World History
= committed Events + frozen Effects

Materialized World State
= Entity / Relationship / Facets

Timeline Logical State
= World Time / logical Work / TimelineVersion / ancestry

Platform Operational State
= lease / fence / retry / worker bookkeeping

Platform Provenance
= Runtime Revision / Execution Session / implementation evidence
```

其中只有 Materialized semantic World State 的变化必须由 committed Event 的 Effect 解释；World Time/Work 等 Timeline logical state 使用 Runtime-owned logical commit；Platform operational state 不进入 World/Timeline semantic history。

### 4.3 Timeline and World Time

一个 World 可以拥有多个 Timeline，但每条 Timeline 只有一份权威 Event Ledger，并拥有自己独立的 World Time / logical future。

Fork 后 sibling Timeline：

- 共享 World identity 与 World Runtime Binding；
- 共享 fork point 之前的 ancestry；
- 从 fork point 复制 logical World Time 和 Pending Work；
- 之后独立推进 World Time、State 和 Future。

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
- 按授权的 Runtime/Timeline control policy 驱动 World Time；
- Fork Timeline 用于实验、预测或反事实分析。

Application 不拥有直接 State mutation 权限，也不因为产品体验不同而重定义 Core semantics。

Application 可以选择 world-time advancement policy（例如手动、next-due jump、paced simulation），但真正修改 Timeline World Time 的动作必须进入 Runtime 的显式 logical authority transition，不能直接改数据库字段或把 wall clock 当 WorldClock。

同一个 World 可以被多个 Application 以不同方式观察和使用；这些 Application 的 Engine 能力入口统一通过 `loom-api`，不直接 import 领域 Capability 或 Storage repository 作为产品功能接口。

## 6. Ownership Test

新增概念时依次判断：

1. **没有它，跨领域的持续 World Runtime 是否无法闭环？** 是 → Core candidate，继续通过 Core Admission Review。
2. **它是否定义一种可复用的世界语义/能力？** 是 → Capability Module。
3. **它是否只是用于创建 World 的能力组合和初始配置？** 是 → World Template。
4. **它是否是某个已经创建的 World 自己长期持有的 identity/binding，或某条 Timeline 的 history/state/time/future？** 是 → World / Timeline。
5. **它是否定义用户目的、展示、分析、交互或运行节奏 policy？** 是 → Application / Runtime policy boundary。

若一个需求横跨多层，应拆分责任，而不是把边界合并。

特别注意：

- `World Runtime Binding` → World-level runtime metadata，不是 Template layer；
- exact Capability implementation → Execution Session / Platform Provenance，不是 World semantic state；
- World Time value → Timeline logical state；
- time advancement policy → Runtime/Application policy；
- committed time transition → Timeline logical history。

这个 Ownership Test 只判断**概念归属**；决定 Rust 类型放在哪个 crate、谁可以依赖谁时，还必须通过 `governance.md` 的 dependency/type-placement rules。

## 7. Stable Boundary

Loom 稳定的顶层模型仍然是：

> **Core -> Capability Module -> World Template -> World <- Application**

可进一步概括为：

```text
Core        → Mechanism
Capability  → Semantics
Template    → Initial Composition / Birth Recipe
World       → Living Instance / Runtime Binding / Reality
Application → Purpose / Experience / Pace Policy
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

完整 World Runtime Closure 以 `docs/architecture/world-runtime.md` 为准。