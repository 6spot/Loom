# Loom Architecture Glossary

> Status: **canonical terminology reference for Loom v0.**
>
> 本文只定义术语。它不单独赋予 Runtime authority；具体行为仍由 `core.md`、`world-runtime.md`、`runtime-contracts.md`、`governance.md` 与 accepted Amendments 决定。若 frozen baseline 与 Amendment 冲突，先查 `docs/architecture/README.md` 的 reverse supersession table。

## World and execution

### World
长期存在的世界 identity 与 runtime boundary。World 不是一次 simulation job，也不是某条 Timeline。

### Timeline
World 中的一条权威历史分支。每条 Timeline 有自己的 Event ordering、materialized State、World Time、logical Work 与 TimelineVersion。

### World Runtime Binding
World-level persistent runtime metadata，描述该 World 允许的 semantic Capability domains、compatibility requirements 与少量 genuinely World-level immutable assembly config。它由同一 World 的 Timelines 共享，不永久 pin exact implementation。

### Installed Capability
当前 Runtime Revision / composition root 中存在的软件实现。Installed 不等于某个 World enabled。

### Enabled Capability
World Runtime Binding 允许 Runtime 为该 World 使用的 semantic Capability domain。

### Execution Session
一次 root world-affecting execution 的审计/执行边界。

### Execution Assembly
一个 Execution Session 开始时 pin 的 exact runtime software environment，包括 target World/Timeline、TimelineVersion、World Runtime Binding、Runtime Revision、exact compatible Capability implementations 与相关 execution policy/services。

### Runtime Revision
平台软件组合/版本的一次可审计 revision。激活新 Revision 只影响之后新启动的 compatible Sessions，不修改 World history、World Time 或 World Runtime Binding。

## History, state and authority

### World History
Committed Event Ledger + frozen Event Effects + Event associations/causality。表示已经确定的语义过去。

### Materialized World State
某条 Timeline 当前的 Entity / Relationship / Facet 现实投影。

### Timeline Logical State
会影响未来 Runtime 执行、且必须可 replay/fork 的 Timeline state，例如 World Time、logical Durable Work、logical schedule order、TimelineVersion、ancestry/fork position，以及 **same-World-Time Chronology Budget consumption**。这些变化只能通过 Runtime-owned Logical Commit 获得权威位置。

### Platform Operational State
只服务运行可靠性的状态，例如 lease、fence、retry `available_at`、attempt count、last technical error、worker bookkeeping。它不是 World History，也不是 Timeline logical history。

### Logical Commit
Runtime-owned 的 Timeline logical-state linearization boundary。它可以包含 committed Events/Effects、logical Work transitions、World Time advancement、chronology-budget consumption 或这些变化的合法组合。

### WorldEffect
由 committed Event 解释的最小 materialized semantic mutation primitive。World Time、Work lifecycle、lease/retry 都不是 WorldEffect。

## Time and scheduler

### World Time / WorldInstant
Timeline-local 单调语义时间坐标。不是 UTC、DB `NOW()`、worker wall clock、EventSeq 或 UUID 时间。

### Platform Time
平台运行时间，用于 lease、retry/backoff、received/committed metadata 等。Platform Time 不自动推进 World Time。

### Effective Due World Time
Durable Work 在 Timeline chronology 上被视为到期的 World Time。`Immediate` 等于 scheduling Logical Commit 的 current World Time；`At(T)` 等于 `T`。

### Semantic Due-ness
Work 的逻辑到期条件：`Pending && effective_due_world_time <= Timeline.world_time`。不依赖 retry backoff、lease、worker availability 或 implementation availability。

### Operational Claimability
在 semantically due 的基础上，平台/Runtime 当前是否允许真正 claim/admit/execute 该 Work。完整 v0 checklist 只以 Amendment 0001 §9 + Amendment 0002 §2 为准；本 glossary 不维护第二份条件清单。

### Logical Schedule Order
Timeline-local、persistent、replayable 的 Work tie-break order。v0 Scheduler order 为 `(effective_due_world_time, logical_schedule_order)`。

### Logical Head
某条 Timeline 上按 frozen Work order 排序后最早的 `Pending` Scheduler-managed Durable Work。

### Head-of-line Chronology Barrier
当 logical head 已 semantically due 时，later Work 不得越过它 claim/execute；World Time 也不得越过当前 due obligations。

### Scheduler Quiescence
当前 Timeline 不存在 semantically due `Pending` Work。只有 scheduler-quiescent 时，automatic World Time advancement 才可能发生。

### Chronology Budget
限制同一 Timeline / WorldInstant 上自动 Scheduler execution 无限展开的 Runtime liveness budget。**其 canonical consumption position属于 Timeline Logical State**，必须可 restart/replay/fork reconstruct。v0 最小 consumption unit 是一次 Scheduler-managed Work 的成功 Logical Commit/completion；technical retry attempts 仍属于 Platform Operational State，由 FailurePolicy 单独约束。Budget exhausted 不是强制推进 World Time 的借口。

### TimelineBlockedOnMissingImplementation
当 semantically due logical head 因 active Runtime Revision 无法组装 compatible handler 而不能执行时，Runtime 对外暴露的 operator-visible liveness condition。它不消耗 technical attempt、不解除 chronology barrier、也不是 World Truth；恢复方式是提供 compatible software 或走受控 logical terminalization。

## Work and failure

### Durable Work
Timeline 上持久、可恢复、尚未决定结果的未来 Runtime execution obligation。

### Technical Retry
同一个 WorkId 的平台级重试。保持同一 semantic due time 与 logical order，只更新 operational attempt/backoff metadata。

### World Reschedule
领域/Runtime 语义决定未来再次处理时，创建一个新的 Work，并获得新的 logical schedule order。

### Dead
Work 的 terminal logical state。进入 `Dead` 必须经 Runtime-owned Logical Commit；它不自动成为 World Event。

### Failure Policy
Runtime policy，决定技术失败后 Retry 还是进入 terminal handling。具体数字可配置，但 v0 自动 retry 必须有界，不能允许一个 poison Work 在没有 operator/policy 出口的情况下永久占据 logical head。

## Input, actions and agency

### ActionInvocation
普通 semantic action request。Capability 解释它“在当前世界意味着什么”。

### Ingress
外部系统进入 Loom 的可靠输入 envelope/boundary。Ingress 携带 identity/idempotency/source/target/time metadata/authorization，并最终路由为 normal Runtime semantic execution；Ingress acceptance 不等于 World Truth。

### Intent
Agency/认知层面的概念：某个 Actor 想尝试什么。v0 **没有 generic Runtime `Intent` protocol type**；Runtime execution 使用 `ActionInvocation` 等明确协议值。

### Actor
一个 Entity 在某次行为/事件中的角色语义，不是 Core persisted subtype。

### Agent
参与 Agency cognition/decision contract 的 Actor/Entity role。v0 不要求在 `loom-core` 中存在 `Agent` persisted subtype/tag。

### Decision
Agency 对“是否尝试一个 Action”的结果。v0 为 `Act(ActionInvocation)` 或 `NoAction`。

## Trigger and reaction

### Trigger
概念 umbrella，不是 v0 第三套 Runtime primitive。

### Temporal Trigger
v0 通过 Durable Work `WorkSchedule::At(WorldInstant)` 表达。

### Event Trigger
v0 通过 Reaction registration 表达：matching committed Event 出现后，Runtime schedules Immediate Durable Work。

### Reaction
对已提交事实的 downstream follow-up registration。Reaction 不直接递归 commit World mutation；它安排后续 Work。

## Template and birth

### World Template
World 的出生配方，不是 subscription。它描述 capability requirements、initial World Time、immutable assembly config 与 ordered bootstrap recipe。

### Validated World Birth Plan
Runtime 对 Template + active software compatibility + dependency closure + bootstrap recipe 校验后的 Runtime-owned birth authority value。它才有资格进入 atomic World creation path。

## Provenance

### Execution Provenance
解释软件当时怎样计算出结果的记录：Session、Runtime Revision、exact implementations、ReadSet、call graph、entropy/cognition evidence、origin、produced Events 等。它不是 World Truth replay authority。

### World Causality
Event ↔ Event 的世界事实因果图。它不能与 execution call graph、Work ordering、Runtime Revision 或 World Time transitions 混用。
