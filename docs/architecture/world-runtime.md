# Loom World Runtime Closure

> Status: **FROZEN — Loom v0 World Runtime architecture baseline.**
>
> 本文补全 Loom 在 `Core -> Capability -> World Template -> World <- Application` 之间缺失的运行契约，并冻结五个 v0 边界：
>
> 1. **一个 World 到底启用了哪些语义能力；**
> 2. **World Time 如何前进；**
> 3. **一次执行如何绑定当前软件实现而不把 World 永久钉死在旧代码；**
> 4. **World Truth、Timeline logical state、Platform operational state 与 Execution Provenance 如何分离；**
> 5. **Durable Work 如何形成不受 retry/lease/数据库偶然顺序影响的 Timeline chronology。**
>
> 本文不增加第六个产品架构层，也不改变既有 Cargo dependency DAG。它定义的是 **World 自身持有的持久执行契约** 以及 Runtime 执行它时必须遵守的 authority boundary。
>
> 本文通过后，改变 World Runtime Binding、World Time、Logical Commit、scheduler chronology 或 Execution Assembly 语义，必须先重新进行 architecture review；普通实现任务不得隐式改变这些规则。

---

## 1. Stable architecture

Loom 的五层语义模型保持不变：

```text
Core
  ↓
Capability Modules
  ↓
World Template
  ↓
World
  ↑
Application
```

但必须补上此前只在文字中隐含、没有成为一等契约的关系：

```text
Installed Capability Implementations
                │
                │ selected by active Runtime Revision
                ↓
        Runtime Execution Host
                │
                │ enforces
                ↓
       World Runtime Binding
                │
                ↓
              World
                │
             Timelines
                │
      Events / State / Work / Time
```

这里的 **World Runtime Binding** 不是新的 Layer。

它是 World 的持久 runtime metadata，回答：

> **这个已经出生的 World 允许 Runtime 使用哪些语义 Capability 来解释未来执行？**

Template 负责出生时生成它；Runtime 每次执行时读取并强制执行它；Template 本身不会继续控制 World。

---

## 2. Six authority domains

Loom 不再使用一个模糊的“World State”同时指代所有持久数据。必须显式区分六个 authority / truth domain。

### 2.1 World identity and runtime binding

```text
WorldId
Template provenance
World Runtime Binding
Capability requirements/configuration
```

它们属于 World-level runtime metadata：

- 与 World identity 一起长期存在；
- 默认由所有 Timeline 共享；
- 不属于某条 Timeline Event Ledger；
- 默认不进入 Agent Context；
- v0 中创建后不可静默修改。

### 2.2 World History

```text
Committed Event Ledger
Frozen Event Effects
Event associations / causality
```

这是已经确定的世界过去。

### 2.3 Materialized World State

```text
Entity existence
Relationship structure/lifecycle
Entity / Relationship Facets
```

这是某条 Timeline 当前现实的 materialized projection。

> **No semantic World State mutation without a committed Event.**

任何 Entity / Relationship / Facet 的语义变化必须由 committed Event 的 frozen Effects 解释。

### 2.4 Timeline Logical State

```text
World Time
TimelineVersion
logical Pending / Completed / Cancelled / Dead Work state
Durable Work effective due instant / logical schedule order
fork ancestry / fork position
other reconstructable Timeline control state
```

这部分会影响未来执行，但不等于领域 World Event。

它可以通过 Runtime-owned **Logical Commit** 改变，不需要伪造领域 Event。

### 2.5 Platform Operational State

```text
Work lease
claim fence
attempt count
retry available_at
last technical error
worker/process bookkeeping
```

它只用于平台运行可靠性：

- 不属于 World History；
- 不属于 Timeline logical history；
- 不推动 World Time；
- 不改变 TimelineVersion；
- fork/replay 不复制它作为语义未来；
- **不能改变 Durable Work 在同一 Timeline 上的逻辑先后顺序。**

### 2.6 Platform History and Execution Provenance

```text
Runtime Revision Ledger
Execution Session
ReadSet
subresolution call graph
Entropy samples
Cognitive executor/provider/model refs
exact Capability implementation refs
Event -> producing Session links
```

它回答“软件当时怎样得出这个结果”，但不是 World Truth。

---

## 3. World Runtime Binding

### 3.1 Installed is not enabled

必须永久冻结以下区别：

```text
Installed Capability
= 当前 Runtime Revision / composition root 中存在某个实现

Enabled Capability
= 目标 World 的 Runtime Binding 允许使用该 Capability semantic domain
```

因此：

> **Registry presence never implies World enablement.**

一个 Runtime 可以安装很多 Capability，但 World A / B / C 可以拥有不同的 enabled set。

```text
Installed: {identity, finance, employment, combat}

World A: {identity, finance}
World B: {identity, employment}
World C: {identity, combat}
```

Runtime 对以下所有语义执行入口都必须先检查 World binding：

- Action dispatch；
- WorkHandler execution；
- Reaction expansion；
- Capability-owned semantic retrieval/index；
- World-scoped Catalog / discovery；
- Runtime-mediated subresolution。

### 3.2 Binding stores semantic requirements, not permanent code pins

World Runtime Binding 保存的是：

```text
CapabilityId
compatible semantic/software version requirement
immutable World-level Capability configuration where genuinely required
binding revision / hash
Template provenance
```

它**不**表示：

```text
World 永远运行 Capability implementation 1.2.3
World 永远运行 Runtime Revision R17
World 永远运行某个 LLM/provider build
```

Exact implementation version 属于某一次 Execution Session 的 provenance。

因此必须区分：

```text
World Runtime Binding
= what semantic capabilities this World permits

Execution Assembly
= which exact current compatible implementations execute this Session
```

### 3.3 Configuration boundary

只有满足以下条件的配置才可以进入 World Runtime Binding：

- 它是 capability assembly 所需；
- 它跨 Timeline 共享；
- 它在 World 出生后不应作为普通世界事实演化；
- 它可以被持久化、版本化、审计。

任何希望随世界历史变化的法律、价格、技术状态、规则、社会条件、角色权限等，都必须进入正常 World State / Event semantics，而不能藏在 Runtime Binding config 中。

> **Runtime Binding is not a hidden mutable domain-state bag.**

### 3.4 v0 immutability

v0 中 World Runtime Binding 创建后视为 immutable。

如果未来需要动态增删 Capability，这必须经过新的 architecture review，明确：

- compatibility / migration；
- historical replay；
- fork；
- old Work semantics；
- provenance；
- schema ownership。

“世界里出现了一项新技术/新制度/新能力”默认仍然通过已有 Capability 的 Event + State 表达，不等于热插拔一个新的 software Capability。

---

## 4. World Template and birth

### 4.1 Template remains a birth recipe

Template 仍然只负责 World 出生：

```text
TemplateId + revision
        ↓
Capability requirements
immutable assembly configuration
initial World Time
ordered bootstrap Actions / initial semantic recipe
        ↓
Validated World Birth Plan
        ↓
World + initial Timeline + World Runtime Binding
```

Template 后续变化不会被已有 World live-read，也不会修改已有 Binding。

> **Template is a birth recipe, not a subscription.**

### 4.2 Template requirements vs bootstrap implementation

Template 可以声明 Capability compatibility requirement，但 World 不因此永久 pin 出生时的 exact implementation。

World birth 时：

```text
Template requirement
        ↓
active Runtime Revision
        ↓
resolve exact compatible implementation
        ↓
bootstrap Execution Session
```

这一次 bootstrap 实际用了哪个 implementation，记录在 Execution Provenance。

World 持久化的是其 semantic requirement / binding，而不是“以后所有执行都必须继续运行出生时的 binary”。

### 4.3 Bootstrap authority

Semantic bootstrap 必须继续遵守正常 authority path：

```text
bootstrap Action
    ↓
Capability Resolver
    ↓
Resolution
    ↓
Runtime validation
    ↓
Event + Effects + Work
    ↓
atomic World birth commit
```

禁止为了初始化方便直接向 Facet/Entity 表写入领域 State。

World/Timeline/Binding 等结构性 birth metadata 本身不需要伪造领域 Event。

---

## 5. Execution Session and Execution Assembly

### 5.1 Every root execution has one pinned software environment

任何可能形成 World Truth 的 root execution 都必须运行在明确的 Execution Session 中，例如：

```text
direct Action
Durable Work
Ingress processing
Agent wake / cognition-driven Action
operator-authorized world execution where applicable
```

Session 开始时 Runtime 一次性确定：

```text
World / Timeline target
pinned TimelineVersion
World Runtime Binding
active Runtime Revision
exact compatible Capability implementations
Execution Policy
controlled Entropy / Cognition services where used
```

这组冻结值构成该 Session 的 **Execution Assembly**。

### 5.2 Session does not switch implementation mid-flight

同一个 root Session：

- subresolution 不得切换到另一套 Runtime Revision；
- registry refresh 不得让 child resolver 使用不同 implementation；
- provider/model config refresh 不得中途替换已经 pin 的 execution environment；
- Commit 前若 Timeline CAS 失效，应按明确 retry/re-resolution policy 处理，而不是偷偷换一套 execution assembly。

### 5.3 Missing compatible implementation

如果 World Binding 允许 Capability A，但 active Runtime Revision 没有满足 binding requirement 的 A implementation：

```text
execution = unavailable / incompatible
World history = unchanged
World binding = unchanged
```

Runtime 不得：

- 自动启用另一个未绑定 Capability；
- 忽略 compatibility requirement；
- 修改 World State 来“修复”软件缺失。

如果缺失的 implementation 对应当前 Timeline 的 head due Work，Scheduler 不得跳过该 Work；该 Timeline 的 scheduler progression 必须保持 blocked，直到实现恢复或该 Work 经显式 Runtime logical transition 离开 `Pending`。

---

## 6. World Time is Timeline logical state

### 6.1 Meaning

`WorldInstant` 是 Timeline-local 的单调语义坐标。

它不是：

- UTC timestamp；
- database `NOW()`；
- worker wall clock；
- EventSeq；
- UUIDv7 timestamp。

同一个 World 的不同 fork Timeline 可以独立推进到不同 World Time。

### 6.2 World Time is not derived from Events

必须废除以下隐式模型：

```text
world_time = max(committed_event.occurred_at)
```

Event 是“在某个 World Time 上发生的事实”，不是让时间前进的唯一发动机。

否则会产生不可闭环状态：

```text
world_time = 10
pending Work due at 20
no external Event

Work cannot run before 20
no Event occurs
world_time never reaches 20
```

### 6.3 Explicit advancement

World Time 只能通过 Runtime authority 的显式 Timeline logical transition 前进：

```text
AdvanceWorldTime
from: T10
to:   T20
```

硬规则：

1. 只能单调前进，不能后退；
2. 必须以 expected TimelineVersion 做 concurrency check；
3. 必须持久化为 reconstructable logical history；
4. 必须产生新的 Timeline logical revision/version；
5. 不要求伪造领域 Event；
6. PlatformClock 不能直接或隐式执行该 transition；
7. replay/fork 必须能精确恢复该 transition 的结果；
8. **存在 semantically due 的 Pending Work 时禁止推进。**

### 6.4 Event time does not advance the clock

v0 中新生成的 World Event 应在 Resolution 所读取的 pinned `world_time` 上发生。

```text
BaseWorldView.world_time = T20
        ↓
Resolver
        ↓
ProposedEvent.occurred_at = T20
```

Runtime 不接受一个 `occurred_at = T30` 的 Event 作为“顺便把 Timeline 从 T20 推到 T30”的机制。

如果领域需要表达：

- source system timestamp；
- legal effective date；
- historical observation time；
- delayed report；

应使用明确的领域 payload/scope/effective-time semantics，而不是偷用 Event timestamp 推进 Runtime World Time。

### 6.5 Platform Time stays operational

`PlatformTime` 只用于：

```text
lease deadline
retry/backoff
received_at
committed_at / audit metadata
worker scheduling
Runtime Revision activation metadata
```

现实服务器经过 30 秒，不会自动让任何 World Timeline 前进 30 个 WorldDuration。

---

## 7. Logical Commit and the corrected mutation law

原先的口号：

> `No mutation without a committed Event.`

需要收窄，否则它会错误地把 Work lifecycle、World Time、fork metadata 等 Runtime-owned Timeline state 逼成假 Event。

新的硬规则是：

> **No semantic World State mutation without a committed Event.**

同时：

> **No Timeline logical-state mutation without a Runtime-owned logical commit.**

### 7.1 Logical Commit may contain

```text
zero or more committed World Events
zero or more frozen World Effects attached to those Events
zero or more logical Work transitions
optional World Time advancement
current Work completion/cancellation where Runtime owns it
resulting TimelineVersion
```

因此合法情况包括：

```text
Event-only commit
Event + Work commit
Work-only logical commit
World-Time-only logical commit
World Time + Work transition commit where contract permits
true NoChange (no logical commit)
```

### 7.2 TimelineVersion

`TimelineVersion` 必须描述完整 logical snapshot position，而不仅是 Event head。

当前 `(head_event_seq, state_revision)` 结构可以继续使用，但 `state_revision` 的语义必须理解为：

> **Timeline logical state revision**

它至少在以下 logical commit 后递增：

- Event / Effect commit；
- Work logical mutation / current Work completion；
- World Time advancement；
- 未来其他影响 replay/fork logical snapshot 的 Timeline transition。

Platform lease/retry bookkeeping 不递增 TimelineVersion。

### 7.3 Logical history is not World Event history

Logical commit journal 是 Runtime reconstruction authority；它不是 Agent 所处世界的“新闻记录”。

```text
World Event Ledger
= determined semantic past

Timeline Logical Journal
= reconstructable execution/time/future-state history

Platform Operational State
= current worker reliability bookkeeping
```

三者不得合并成一张模糊 history table 或一个统一 Event enum。

---

## 8. Scheduler, quiescence and time progression

Scheduler 必须把 **World chronology** 与 **platform execution eligibility** 分开。

它依次回答四个问题：

```text
1. Which Pending Work is semantically due at current World Time?
2. Which one is the deterministic logical head?
3. Is that head operationally claimable right now?
4. Only when no semantically due Pending Work exists: should policy advance World Time?
```

### 8.1 Semantic due-ness vs operational claimability

`semantically due` 只由 Timeline logical state 决定：

```text
logical status = Pending
AND
effective_due_world_time <= Timeline.world_time
```

它**不**取决于：

```text
retry available_at
lease expiration
worker availability
current process health
current compatible implementation availability
```

`operationally claimable` 则是在 semantically due 的基础上再要求：

```text
available_at <= PlatformTime.now
no unexpired valid lease
compatible handler implementation available in current Runtime Revision
other purely operational claim/fence conditions satisfied
```

因此一个 Work 可以：

```text
semantically due = true
operationally claimable = false
```

这时它仍然是 Timeline chronology 上尚未解决的当前义务。

> **Platform ineligibility may delay execution; it may not erase or reorder semantic due-ness.**

### 8.2 Effective due World Time

为了形成统一逻辑顺序，所有 Pending Work 都必须有可比较的 **effective due World Time**。

概念上：

```text
Immediate
→ effective_due_world_time = World Time of the logical commit that schedules it

At(T)
→ effective_due_world_time = T
```

是否物理存储为一个字段由实现决定；语义必须可持久、可 replay、可 fork。

### 8.3 Deterministic logical Work order

同一 Timeline 的 Scheduler 不得使用以下因素决定 Work 先后：

```text
PostgreSQL natural row order
UUID / UUIDv7 generation time
worker race
wall-clock arrival race
HashMap iteration order
lease acquisition speed
```

v0 必须为每个 scheduled Work 建立持久、Timeline-local 的 **logical schedule order**。

概念排序键冻结为：

```text
(effective_due_world_time, logical_schedule_order)
```

规则：

1. `logical_schedule_order` 在 Schedule 所属 Logical Commit 中确定；
2. 同一个 Logical Commit 创建多个 Work 时，按 validated `WorkMutation` 的稳定顺序分配；
3. 新 Immediate Work 在当前 World Time 获得新的后续 order，不插到已经存在的同一时刻 Work 前面；
4. Fork 克隆 Pending Work 时可以分配新的 branch-local `WorkId`，但必须保持 inherited Work 的相对 logical order；
5. child Timeline 后续新 Work 的 order 必须位于其已继承 logical order high-water mark 之后；
6. replay 必须恢复同一顺序。

这意味着 Reaction 产生的 Immediate Work 如果要与当前事实**原子同时成立**，就不应依赖 scheduler 插队；该语义应使用 atomic subresolution。Reaction Work 本来就是“事实已成立之后的后续处理”。

### 8.4 Head-of-line rule

在某个 Timeline 上，Scheduler-managed Durable Work 的 logical head 是排序键最小的 `Pending` Work。

当 logical head 已经 semantically due：

- 只有该 head 可以被 Scheduler admission/claim；
- 后面的同时间 Work 不能先执行；
- 更晚 World Time 的 Work 更不能越过它；
- head 正被有效 lease 持有时，后面的 Work 仍不得被 claim；
- head 处于 retry backoff 时，后面的 Work 仍不得被 claim；
- head 暂时缺少 compatible implementation 时，后面的 Work 仍不得被 claim。

这形成一个明确的 **head-of-line chronology barrier**。

不同 Timeline 之间没有这个共享顺序，可以独立、并行推进。

### 8.5 Due-work quiescence barrier

只要当前 Timeline 存在任何 semantically due 的 `Pending` Work：

> **World Time advancement is forbidden.**

因此：

```text
World Time = T20
W1 due T20, retry available_at = platform P200
W2 due T30
current platform time = P100
```

合法状态是：

```text
Timeline remains at T20
W1 remains logical head / semantically due
Scheduler waits for operational eligibility or explicit logical resolution
W2 remains future
```

禁止：

```text
skip W1
AdvanceWorldTime T20 -> T30
run W2
```

否则一次纯技术 retry/backoff 就会改变 World chronology。

### 8.6 Leaving the barrier

一个 head Work 只有在 Runtime-owned Logical Commit 后离开 `Pending`，例如：

```text
Completed
Cancelled
Dead
```

技术 retry 本身不会改变 logical status，因此不会解除 barrier。

如果 retry/failure policy 最终决定把 Work 标记为 `Dead`，`Dead` 必须作为明确的 logical Work transition 持久化并推进 TimelineVersion；不能通过删除行或只写 operational error 偷偷消失。

如果某个世界需要把“任务失败/取消”本身变成 Agent 可知的世界事实，Capability 仍必须显式产生对应 Event；Runtime logical status 不自动成为 World Event。

### 8.7 Time advancement policy

Core 定义显式 advancement mechanism，但不写死“世界应该多快运行”。

Application / Runtime policy 可以实现：

```text
manual/external advancement
jump to next due Work
paced simulation
real-world mirror mapping
custom policy
```

但调用 `AdvanceWorldTime` 前必须先证明当前 Timeline **scheduler-quiescent**：

```text
no semantically due Pending Work
```

若采用 next-due policy，目标应是最小 future `effective_due_world_time`。

### 8.8 Auto-advance safety

自动推进策略至少必须遵守：

1. 当前存在 semantically due Pending Work 时绝不推进 World Time；
2. operationally unclaimable 的 due head 会阻塞 scheduler progression，而不是被跳过；
3. 默认跳转目标是最小 future effective due WorldInstant，不任意越过；
4. advance commit 与之后 Work execution 是两个可恢复边界；
5. Runtime 在 advance 成功后崩溃，重启后仍应看到新的 World Time，并从 deterministic logical head 继续；
6. worker crash/retry、lease expiry、PlatformClock passage 不能触发 world-time transition；
7. 同一 Timeline 的 Scheduler Work admission 不允许用 worker concurrency 打乱 logical order。

### 8.9 Scope of this ordering law

本节冻结的是：

```text
Scheduler-managed Durable Work ordering
+
automatic World Time advancement barrier
```

它**不**在 v0 强行定义“所有外部 Action / Ingress / Operator command / scheduler Work 共享一个全局 total-order input queue”。这些其他 root inputs 仍通过各自显式边界进入 Runtime，并最终由 Timeline CAS 线性化；其来源/执行必须进入 provenance。

因此：

- Scheduler 不能因为平台偶然性重排自己的 Work；
- Platform failure 不能让 Scheduler 跳到更晚 Work/World Time；
- 外部输入在同一 World Time 的 admission policy 是独立问题，不隐式伪装成 scheduler ordering。

如果未来需要完全 deterministic 的“所有 root inputs 单一序列”，必须单独进行 architecture review。

### 8.10 Priority

v0 不允许一个未持久、仅供 worker 使用的 `priority` 改变同一 Timeline 的 logical Work chronology。

未来如果需要 semantic scheduling priority，它必须成为明确、持久、可 replay/fork 的 logical ordering contract，并重新评审其与 `(effective_due_world_time, logical_schedule_order)` 的关系。

---

## 9. Replay and Fork

### 9.1 Replay uses two reconstructable histories

历史重建必须明确分工：

```text
Committed Events + frozen Effects
        ↓
Entity / Relationship / Facet materialized World State

Timeline Logical Commit Journal
        ↓
World Time + logical Durable Work + logical Timeline position
```

Replay 不能：

- 重新调用 current Resolver；
- 重新抽 Entropy；
- 重新调用 Cognitive Executor；
- 用 Platform timestamps 猜 World Time；
- 用当前 Work table 假装历史 Work 状态；
- 通过 `max(event.occurred_at)` 推导历史 World Time；
- 用数据库当前行序重新决定 historical Work ordering。

### 9.2 Fork

Fork 在一个明确 `TimelineVersion` 上复制 logical snapshot：

```text
same World identity
same World Runtime Binding
new Timeline identity
reconstructed materialized State
reconstructed World Time
cloned logical Pending Work with new branch-local WorkId
preserved effective due time + relative logical schedule order
reset Platform operational claim/retry state
```

World Runtime Binding 属于 World，所以 sibling Timelines 不能拥有不同 enabled Capability set。

如果未来需要 per-Timeline semantic assembly，那是新的架构能力，不属于 v0。

---

## 10. Execution Host and controlled nondeterminism

### 10.1 Capability gets a host contract, not platform resources

Capability Resolver / WorkHandler 只能看到 Runtime 提供的受控 execution host projection。

至少包括：

```text
pinned BaseWorldView
Timeline identity / version / World Time
Resolution budget
Runtime-mediated subresolution
explicit Entropy request boundary where allowed
current Work execution metadata where semantically required
```

它不能收到：

```text
PlatformClock
raw RNG
PgPool / transaction
network client
provider SDK
Commit handle
mutable Capability registry
```

### 10.2 World Time is read-only to Capability

Capability 可以读取 `BaseWorldView.world_time()`，但不能调用系统时钟决定 World Time，也不能直接推进 Timeline clock。

如果领域行为需要“稍后再判断”，Resolver 应 Schedule `WorkSchedule::At(WorldInstant)`；是否以及何时推进到那个时间由 Runtime/Application time policy 决定。

### 10.3 Entropy is explicit

任何影响 Resolution 的随机性必须：

```text
Capability request
    ↓
Runtime Entropy boundary
    ↓
controlled sample
    ↓
Execution Provenance
```

Capability 内部禁止直接调用 OS RNG / `thread_rng()` / hidden random source。

Replay 永不重新采样。

### 10.4 Cognition remains an Agency boundary in v0

v0 默认不把任意 Cognitive Provider 作为通用 `ResolutionContext` 网络能力暴露给所有 Capability。

标准路径是：

```text
Agent-local Context
    ↓
Cognitive Executor (loom-agency SPI)
    ↓
Decision::Act(ActionInvocation) / NoAction
    ↓
normal Runtime + Capability authority path
```

未来如果某类领域 Resolver 确实需要 external inference，必须单独设计 explicit host service、provenance、failure/replay semantics，不能通过 generic network/provider handle 绕过本节原则。

---

## 11. Runtime Revision and implementation evolution

### 11.1 World does not upgrade to a Runtime Revision

平台软件变化继续遵守：

> **Worlds evolve; software upgrades. Never confuse the two.**

Runtime Revision activation：

- 不修改 World Event；
- 不修改 Materialized World State；
- 不修改 World Runtime Binding；
- 只影响之后新启动的 compatible Execution Session。

### 11.2 Binding requirement vs implementation provenance

必须使用两个不同概念：

```text
World Runtime Binding
Capability A: compatible requirement ^1.x

Execution Session S100
Runtime Revision R18
Capability A implementation 1.7.3
```

如果未来激活 R19：

```text
Capability A implementation 1.8.0
```

只要仍满足 World binding，新的 Session 可以使用 1.8.0；旧 Event 仍通过 provenance 指向 S100 / R18 / 1.7.3。

### 11.3 Provenance bridge

```text
Committed Event
      ↓ produced_by
Execution Session
      ↓
Runtime Revision
Exact Capability Implementation(s)
Execution Policy
ReadSet
Entropy/Cognition evidence
```

这个图用于人类审计，不参与 World replay authority。

---

## 12. World birth, execution and evolution — complete map

```text
                 PLATFORM SOFTWARE

      Installed Capability Implementations
                     │
              Runtime Revision
                     │
                     ▼

TEMPLATE ------------------------------------------
TemplateId / revision
Capability requirements
initial World Time
bootstrap recipe
        │
        ▼
Validated World Birth Plan
        │
        ▼
WORLD ---------------------------------------------
WorldId
World Runtime Binding
Template provenance
        │
        ├────────────────────────────────────┐
        │                                    │
        ▼                                    ▼
Timeline A                              Timeline B (fork)
World Time                              World Time
Event Ledger                            Event Ledger ancestry
Materialized State                      Materialized State
Logical Work                            Logical Work
        │                                    │
        └──────────────┬─────────────────────┘
                       │
                       ▼
               Root Execution Session
               - target World/Timeline
               - pinned TimelineVersion
               - Runtime Revision
               - exact compatible implementations
               - execution/provenance context
                       │
                       ▼
                  Resolution
                       │
                       ▼
             Runtime Validation / CAS
                       │
                       ▼
                  Logical Commit
             ┌─────────┼──────────┐
             ▼         ▼          ▼
          Events     Work       World Time
          Effects  transitions  transition
                       │
                       ▼
             deterministic scheduler head
                       │
           due-work quiescence barrier
```

---

## 13. Hard invariants after closure

以下约束属于 architecture-level invariants：

1. **Installed Capability != enabled Capability for a World.**
2. **World Runtime Binding is World-level and shared by its Timelines.**
3. **World Runtime Binding records semantic requirements, not a permanent Runtime/implementation pin.**
4. **Template produces a World birth recipe; existing Worlds never live-read Template.**
5. **No semantic World State mutation without a committed Event.**
6. **No Timeline logical-state mutation without a Runtime-owned logical commit.**
7. **World Time is explicit, Timeline-local, monotonic logical state.**
8. **Event occurrence does not implicitly advance World Time.**
9. **Platform Time never implicitly advances World Time.**
10. **Semantic Work due-ness is Timeline logical state; retry/lease/platform eligibility cannot erase it.**
11. **A semantically due Pending Work is a World-Time advancement barrier.**
12. **Scheduler-managed Work in one Timeline follows persistent `(effective due World Time, logical schedule order)` chronology.**
13. **Database row order, UUID order, worker race, lease speed and wall-clock race never define same-Timeline Work order.**
14. **A due logical head cannot be skipped because it is retrying, leased, temporarily unavailable or missing a compatible implementation.**
15. **Replay reconstructs World State from frozen Event Effects and World Time/Work/order from logical history.**
16. **Fork inherits World binding, fork-point World Time and logical future/order, but resets branch-local operational state.**
17. **Every root world-affecting execution pins one Execution Assembly for its Session.**
18. **Capability receives host-controlled boundaries, never raw platform authority/resources.**
19. **Exact implementation versions belong to Execution Provenance.**
20. **Runtime Revision activation changes future software execution, never past World history.**

---

## 14. Consequences for existing architecture documents

本文冻结后，其他 normative documents 必须按以下解释同步：

### `core.md`

- 将 `No mutation without a committed Event` 收窄为 semantic World State mutation；
- 明确 World Time 是 Timeline logical state；
- Scheduler 同时依赖 explicit time advancement + due Work，而不是等待 Event 自己把时间推过去；
- semantically due Pending Work 构成 World-Time advancement barrier。

### `layers.md`

- 五层结构不增加新层；
- World 明确持有 World Runtime Binding；
- Template 生成 Binding，但不持续拥有 Binding。

### `runtime-contracts.md`

- World creation / dispatch / Work / Reaction / Catalog 都必须 world-binding-aware；
- Logical Commit 包含 World Time transition；
- Event `occurred_at` 不再是推进 clock 的机制；
- ResolutionContext 不承诺 raw clock/network/provider access；
- Durable Work 必须区分 semantic due-ness 与 operational claimability；
- same-Timeline scheduler ordering 必须持久、确定、可 replay/fork。

### `evolution.md`

- World semantic Capability requirement 与 exact Capability implementation version 分离；
- exact implementation binding 单位仍然是 Execution Session。

### `implementation.md`

- Runtime 的 global registry 只能表示 installed implementations；
- World execution 必须额外加载/强制 World Runtime Binding；
- replay storage 需要 logical time/work/order transition history；
- persistence authority 要区分 World history、logical timeline state、operational state、platform provenance；
- Work claim/query 不能把 `available_at` 误当成 semantic due-ness，也不能跳过 logical head。

### `governance.md`

现有 Cargo DAG 不需要因本文改变。新增 contract/type 仍按“port belongs to the abstraction that requires it”的规则落位，禁止为了 World Binding、Time progression 或 scheduler ordering 反向引入 Storage/Runtime dependencies。

---

## 15. Non-goals of this closure

本文现在**不**决定：

- 具体 Rust struct/function/field 名称；
- PostgreSQL table/schema/index；
- Scheduler polling interval；
- World Time 自动推进 policy 的默认产品配置；
- 所有外部 root input 的全局 total ordering；
- dynamic Capability hot-plug/migration；
- 生产 LLM/provider 实现；
- Runtime Change Ledger 的完整 Admin API；
- Issue/Milestone 顺序。

这些都必须在本架构 baseline 下重新规划，而不能继续沿用旧实现假设。

---

## 16. Closure statement

Loom 的持续 World 闭环现在冻结为：

```text
World identity
+ World Runtime Binding
+ Timeline History
+ Materialized World State
+ Timeline Logical State
    - World Time
    - logical Durable Work
    - persistent Work chronology
+ explicit Runtime execution boundaries
+ due-work quiescence before time advancement
+ separate Platform Operational State
+ separate Execution Provenance / Runtime Change History
```

最终原则：

> **A World owns its semantic execution contract; Runtime owns authority; a Session owns the exact software binding; Events own the determined past; Logical Commits own reconstructable time/future transitions; the Scheduler preserves logical chronology; Platform state owns only operational reliability.**
