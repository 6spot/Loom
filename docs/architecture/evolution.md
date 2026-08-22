# Loom World Evolution and Runtime Change

> Status: confirmed architectural baseline after World Runtime Closure review.

本文处理一个核心边界：**World 自己的演化、World 的长期 semantic runtime binding、以及 Loom 平台软件实现的变化不是同一种历史。**

> **Worlds evolve; software upgrades. Never confuse the two.**
>
> **世界只会演化，软件才会升级。**

完整 World Runtime Binding / Execution Session contract 见 `world-runtime.md`。

## 1. World Evolution

World 中的法律、制度、规则、技术、社会能力和实体状态都通过自己的历史演化。

```text
old world condition
        ↓
World Event / Rule Change
        ↓
new condition becomes effective
        ↓
future world behavior changes
```

新规则不会“升级过去”。它只按照自己的 effective time、scope 和 transition semantics 影响之后的世界行为。

例如：

```text
Rule A
valid until World Time T100

Rule B
valid from World Time T100
```

T100 之前已经发生的 Event 不会因为 Rule B 出现而改变。

同理，新的科技、制度状态、角色能力或世界内“可用能力”出现，是 World 自己的历史事实；并不意味着 World software package 被升级或新增一个 Runtime Capability implementation。

> **In-world capability/affordance evolution is not software Capability hot-plug.**

## 2. World Runtime Binding

一个已经出生的 World 持有持久的 **World Runtime Binding**。

它描述：

```text
enabled Capability semantic domains
compatible Capability requirements
immutable World-level assembly configuration where required
binding revision/hash
Template/birth provenance
```

它属于 World-level runtime metadata：

- 与 World identity 一起长期存在；
- 默认由该 World 的所有 Timeline 共享；
- 不属于某条 Timeline Event Ledger；
- 不等于 exact software implementation；
- v0 中创建后不可静默修改。

必须永久区分：

```text
World Runtime Binding
= what semantic capabilities this World permits

Runtime Revision / Capability implementation
= what software executes a particular Session
```

如果未来确实需要动态修改 World Runtime Binding，必须单独设计 migration/replay/fork/old-Work/provenance semantics；不能把它当成普通配置热更新。

## 3. Template is a birth recipe

World Template 只负责创建 World 时的初始组合：

```text
Capability requirements
immutable assembly configuration
initial rules/defaults
initial World Time
bootstrap Action recipe
```

Template 经过 Runtime validation 后生成 World Birth Plan，并形成新 World 的 Runtime Binding。

World 一旦创建，就沿自己的 Timeline 独立演化。

Template 后续改变只影响之后创建的 World；已有 World 不持续与 Template 同步。

> **Template is a birth recipe, not a subscription.**

### 3.1 Template revision does not mean permanent code pin

Template 可以声明 Capability compatibility requirement，但出生时解析到的 exact implementation 只属于 bootstrap Execution Session provenance。

例如：

```text
Template requirement:
identity.basic ^1
finance.basic ^2

World Runtime Binding:
identity.basic ^1
finance.basic ^2

Birth Session S1:
Runtime Revision R17
identity.basic implementation 1.4.2
finance.basic implementation 2.1.0
```

World 不因为 S1 使用这些 binaries，就永久绑定 R17 / 1.4.2 / 2.1.0。

## 4. Software / Runtime Change

Core、Capability implementation、Cognitive Executor、Execution Policy、Storage/Runtime implementation 等代码会随着开发持续修复和变化。

这些变化属于 **Platform History**，不是 World History。

平台使用独立的 **Runtime Change Ledger** 记录：

```text
runtime revision
published / activated Platform Time
core build/ref
capability implementation refs
execution policy/provider refs where appropriate
change summary
semantic_behavior_changed?
```

Runtime Change Ledger 可以被开发者和 Operator 审计，但默认不能进入 Agent Context，也不属于任何 World Timeline。

Runtime Revision activation本身：

- 不提交 World Event；
- 不修改 Materialized World State；
- 不推进 World Time；
- 不修改 World Runtime Binding；
- 只改变之后新 Execution Session 可选择的软件环境。

## 5. New execution uses the active compatible engine

正常运行中的 World 不需要执行 `upgrade()`。

新的 Runtime Revision 激活以后：

> **之后新启动的 Execution Session 使用当前激活且满足目标 World Runtime Binding 的兼容 Runtime Revision / Capability implementations。**

Binding 单位是 Execution Session，而不是整个 World。

```text
Work / Action / Ingress
          ↓ start
Execution Session
          ↓
load target World Runtime Binding
          ↓
bind active Runtime Revision
          ↓
resolve exact compatible Capability implementations
          ↓
freeze Execution Assembly
          ↓
Execute / Resolve / Commit / Yield
          ↓
Session ends
```

一次 Session 开始后不在中途切换 Runtime Revision 或 Capability implementation。

如果 active revision 无法满足目标 World Binding：

```text
execution unavailable/incompatible
World unchanged
Binding unchanged
```

Runtime 不得自动启用另一个未绑定 semantic domain，也不得忽略 compatibility requirement。

## 6. Ongoing world processes do not pin old code

“世界中的一件事情正在持续”与“Runtime 正在进行一次计算”不是同一概念。

例如旅行在 R17 期间开始：

```text
World Time T10
TRAVEL_STARTED
schedule completion Work at T20

Platform Time P500
R18 activated

World Time explicitly advances to T20
completion Work starts
→ new Execution Session
→ resolves current World Binding against R18
→ uses compatible current implementations
```

旅行作为 World 中的持续活动，不会因为开始时使用 R17，就永久绑定旧代码。

如果某个旧合同、旧案件或旧规则仍需要依据旧法律处理，这是 **World Rule Semantics**，应由 Capability 根据 World Time、effective scope、grandfathering 等规则表达，而不是通过运行旧 Runtime binary 实现。

## 7. World Time evolution is not software evolution

World Time 是 Timeline logical state，不是 Platform Change Ledger 的时间轴。

必须区分：

```text
World Time advancement
= explicit Runtime-owned Timeline logical transition
= affects what future Work is due and what World rules are current

Platform Time passage
= lease/retry/audit/runtime activation metadata
= does not implicitly advance a World
```

例如服务器从 P500 运行到 P800，不代表任何 World 自动从 T10 变成 T310。

如果 Runtime/Application policy 决定推进 World Time，必须产生显式、可重建的 logical time transition。

## 8. Past events never change automatically

如果 R17 中存在 Bug：

```text
R17 / Session S100
↓
Event E100 committed
↓
State consequence already formed
```

R18 修复 Bug 后：

- E100 不重新 Resolve；
- E100 的 Effects 不修改；
- 已经形成的 State consequence 不静默纠正；
- 新 Execution Session 使用修复后的 compatible 实现。

> **Bug Fix changes future execution behavior; it does not rewrite committed history.**

如果运营者需要纠正当前世界结果，应产生显式 World correction/intervention Event；如果需要研究“没有这个 Bug 的历史会怎样”，应从过去 Fork 并 re-simulate，而不是覆盖原 Timeline。

## 9. Technical fix vs semantic behavior change

软件变化可以分成：

### Semantics-preserving change

例如：

```text
performance
cache
memory leak
logging
internal storage implementation
```

这类变化不应改变 World semantics。

### Semantics-changing change

例如：

```text
fix incorrect resolver logic
change decision routing
change stochastic algorithm
change capability behavior
```

这类变化允许影响激活之后的新 compatible Execution Session，但必须在 Runtime Change Ledger 中可识别、可审计。

无论哪一种，都不能重写 committed World History。

如果新 implementation 已经不满足某 World Runtime Binding 的 compatibility requirement，它不能通过“当前平台版本更新了”自动进入该 World 的执行环境。

## 10. Execution Provenance bridges the histories

World Timeline、World Runtime Binding 与 Runtime Change Ledger 不合并，但可以通过 **Execution Provenance** 关联。

```text
World Event E103
      ↓ produced_by
Execution Session S100
      ↓
World Runtime Binding hash B7
Runtime Revision R18
Capability implementation X 1.7.3
Execution Policy P12
Cognitive / Entropy refs if relevant
```

因此 Operator 可以回答：

```text
这个 World 允许什么 semantic capability？
→ World Runtime Binding

这次执行实际用了哪个软件版本？
→ Execution Session provenance

World 当时发生了什么？
→ Event Ledger

平台何时切换了实现？
→ Runtime Change Ledger
```

但 `R18 activated` 不是 World Event，也不会被 Agent 感知，除非某个 Application 明确把该平台事实重新作为外部信息通过 Ingress 注入 World。

## 11. Replay and alternative history

必须继续保持：

```text
Historical Replay
→ committed Event Effects reconstruct semantic State
→ Timeline logical history reconstructs World Time / logical Future
→ never reruns old software

Counterfactual Re-simulation
→ fork from historical snapshot
→ run new future Execution Sessions
→ may use current compatible software
```

Replay 不需要旧 Runtime Revision 才能恢复 World Truth，因为 authoritative World outcome 已经冻结在 committed Events/Effects 和 logical Timeline history 中。

Execution Provenance 保存“当时怎么算出来的”；它不是 replay dependency。

## 12. Stable distinction

最终保持五种机制完全分离：

```text
World Evolution
→ Events / Rules / Materialized State / effective World Time semantics
→ changes the living world

World Runtime Binding
→ persistent semantic capability contract for one World
→ determines what semantic domains future execution may use

Timeline Logical Evolution
→ World Time / Durable Work / fork position / logical revision
→ reconstructable future/time control state

Platform Evolution
→ Runtime Change Ledger / Runtime Revision
→ changes future software implementation availability

Alternative History
→ Fork + re-simulation
→ creates another Timeline without rewriting the original
```

这五者不能使用一个笼统的 `upgrade world` / `update world config` 概念混在一起。