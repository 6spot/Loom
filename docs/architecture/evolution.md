# Loom World Evolution and Runtime Change

> Status: confirmed architectural baseline.

本文只处理一个边界：**World 自己的演化，与 Loom 平台软件实现的变化不是同一种历史。**

> **Worlds evolve; software upgrades. Never confuse the two.**
>
> **世界只会演化，软件才会升级。**

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
valid until 2026-05-31

Rule B
valid from 2026-06-01
```

2026-05 已经发生的 Event 不会因为 Rule B 出现而改变。

同理，新的科技或能力出现，是 World 自己的历史事实；并不意味着 World package 被升级。

## 2. Template is a birth recipe

World Template 只负责创建 World 时的初始组合：

```text
capabilities
initial rules
initial defaults
initial configuration
```

World 一旦创建，就沿自己的 Timeline 独立演化。

Template 后续改变只影响之后创建的 World；已有 World 不持续与 Template 同步。

> **Template is a birth recipe, not a subscription.**

## 3. Software / Runtime Change

Core、Capability implementation、Cognitive Executor、Execution Policy 等代码会随着开发持续修复和变化。

这些变化属于 **Platform History**，不是 World History。

平台使用独立的 **Runtime Change Ledger** 记录：

```text
runtime revision
published / activated time
core build/ref
capability implementation refs
change summary
semantic_behavior_changed?
```

Runtime Change Ledger 可以被开发者和 Operator 审计，但默认不能进入 Agent Context，也不属于任何 World Timeline。

## 4. New execution uses the active engine

正常运行中的 World 不需要执行 `upgrade()`。

新的 Runtime Revision 激活以后：

> **之后新启动的 Execution Session 使用当前激活的兼容 Runtime Revision。**

Binding 单位是 Execution Session，而不是整个 World。

```text
Work
 ↓ start
Execution Session
 ↓ bind active Runtime Revision
Execute / Resolve / Commit / Yield
 ↓
Session ends
```

一次 Session 开始后不在中途切换 Runtime Revision。

尚未开始的 Durable Work 只是 unresolved future execution，因此它真正开始执行时使用当时当前引擎，而不是创建 Work 时的旧引擎。

## 5. Ongoing world processes do not pin old code

“世界中的一件事情正在持续”与“Runtime 正在进行一次计算”不是同一概念。

例如旅行在 R17 期间开始：

```text
10:00 TRAVEL_STARTED
      schedule completion Work

10:30 R18 activated

13:00 completion Work starts
      → new Execution Session
      → uses R18
```

旅行作为 World 中的持续活动，不会因为开始时使用 R17，就永久绑定旧代码。

如果某个旧合同、旧案件或旧规则仍需要依据旧法律处理，这是 **World Rule Semantics**，应由 Capability 根据 effective time、scope、grandfathering 等规则表达，而不是通过运行旧 Runtime 代码实现。

## 6. Past events never change automatically

如果 R17 中存在 Bug：

```text
R17
↓
Event E100 committed
↓
State consequence already formed
```

R18 修复 Bug 后：

- E100 不重新 Resolve；
- E100 的 Effects 不修改；
- 已经形成的 State consequence 不静默纠正；
- 新 Execution Session 使用修复后的实现。

> **Bug Fix changes future execution behavior; it does not rewrite committed history.**

如果运营者需要纠正当前世界结果，应产生显式 World correction/intervention Event；如果需要研究“没有这个 Bug 的历史会怎样”，应从过去 Fork 并 re-simulate，而不是覆盖原 Timeline。

## 7. Technical fix vs semantic behavior change

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

这类变化允许影响激活之后的新 Execution Session，但必须在 Runtime Change Ledger 中可识别、可审计。

无论哪一种，都不能重写 committed World History。

## 8. Execution Provenance bridges the two histories

World Timeline 与 Runtime Change Ledger 不合并，但可以通过 **Execution Provenance** 关联。

```text
World Event E103
      ↓ execution_ref
Execution Session S100
      ↓
Runtime Revision R18
Capability Implementation X
Execution Policy P12
Cognitive / Entropy refs if relevant
```

因此 Operator 可以在同一个时间视图中叠加查看：

```text
World Events
E100 ─ E101 ───── E102 ─ E103
                   ↑
             R18 activated

Platform Changes
R17 ────────────── R18
```

但 `R18 activated` 不是 World Event，也不会被 Agent 感知，除非某个 Application 明确把该平台事实重新作为外部信息通过 Ingress 注入 World。

## 9. Stable distinction

最终保持三种机制完全分离：

```text
World Evolution
→ Events / Rules / State / effective time
→ changes the living world

Platform Evolution
→ Runtime Change Ledger / Runtime Revision
→ changes future execution implementation

Alternative History
→ Fork + re-simulation
→ creates another Timeline without rewriting the original
```

这三者不能使用一个笼统的 `upgrade world` 概念混在一起。