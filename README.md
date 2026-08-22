# Loom

> **Loom lets you create worlds that keep living.**

Loom 是一个用于构建、运行和扩展**持续演化智能世界**的开放引擎。

Loom 不以 MiroFish 的工程结构为基础，也不追求对其实现兼容。MiroFish 只作为历史源码与设计参考保留在 Git 历史/上游仓库中；当前工作树从 Loom 自己的架构重新开始。

## Architecture first

Loom 的权威设计来自：

- [`docs/vision.md`](docs/vision.md) — 项目愿景与完整世界运行图景
- [`docs/principles.md`](docs/principles.md) — **冻结的跨领域硬原则**
- [`docs/architecture/core.md`](docs/architecture/core.md) — Core v0 Conceptual Closure
- [`docs/architecture/layers.md`](docs/architecture/layers.md) — 产品/世界五层语义层级
- [`docs/architecture/world-runtime.md`](docs/architecture/world-runtime.md) — **冻结的 World Runtime Binding、World Time、Logical Commit、Durable Work chronology、Execution Session 闭环契约**
- [`docs/architecture/evolution.md`](docs/architecture/evolution.md) — World Evolution、World Binding 与 Runtime Change
- [`docs/architecture/runtime-contracts.md`](docs/architecture/runtime-contracts.md) — **冻结的 Runtime / Capability / Effect / Durable Work 详细执行契约**
- [`docs/architecture/implementation.md`](docs/architecture/implementation.md) — Loom v0 技术基线、依赖与数据权威
- [`docs/architecture/governance.md`](docs/architecture/governance.md) — **强制 Rust 依赖方向、authority type placement、统一 Loom API 暴露与架构变更规则**

建议阅读顺序：

```text
vision
  ↓
principles
  ↓
core + layers
  ↓
world-runtime
  ↓
runtime-contracts + evolution
  ↓
implementation + governance
```

`world-runtime.md` 是当前冻结架构闭环的中心文档；`runtime-contracts.md` 是 Core/Protocol/Runtime/Capability 公共抽象的直接执行语义依据；`governance.md` 是所有开发必须遵守的 Rust 物理依赖、authority placement 与公开能力治理规范。根目录 [`AGENTS.md`](AGENTS.md) 提供开发者/编码 Agent 的执行守则。

代码中的公开抽象必须使用 Rust doc comments 记录其意义、所有权、Truth/authority domain、权限、禁止事项、持久化与一致性规则，不能要求维护者通过聊天记录猜测设计意图。

## Frozen runtime distinctions

Loom v0 明确区分：

```text
Installed Capability
= platform software availability

World Runtime Binding
= one World's semantic enablement / compatibility contract

Execution Assembly
= exact software implementations pinned for one root Session
```

同时区分：

```text
World History
= committed Events + frozen Effects

Materialized World State
= Entity / Relationship / Facets

Timeline Logical State
= World Time / logical Work / logical Work order / TimelineVersion / ancestry

Platform Operational State
= lease / fence / retry / worker bookkeeping

Platform History / Execution Provenance
= Runtime Revision / Sessions / exact implementation evidence
```

两个核心 mutation law：

> **No semantic World State mutation without a committed Event.**
>
> **No Timeline logical-state mutation without a Runtime-owned logical commit.**

World Time 是显式 Timeline logical state；Event timestamp 和 PlatformClock 都不能隐式推动它。

### Durable Work chronology

Scheduler chronology 同样已经冻结：

```text
semantic due-ness
= Pending + effective due World Time <= current World Time

operational claimability
= semantic due
  + retry available_at satisfied
  + no valid lease
  + compatible implementation available
```

两者不能混。

同一 Timeline 的 Scheduler-managed Work 使用：

```text
(effective_due_world_time, logical_schedule_order)
```

形成持久、可 replay/fork 的逻辑顺序。

因此：

- UUID/WorkId、数据库 natural row order、worker race、wall-clock race、lease acquisition speed 都不能定义 Work 顺序；
- 只有当前 semantically due logical head 可以被 Scheduler admission/claim；
- retry/backoff、active lease、worker crash 或 temporarily missing implementation 都不能让 later Work 越过 head；
- 只要存在 semantically due Pending Work，World Time 就不能继续前进；
- head 只有通过 Runtime-owned Logical Commit 进入 `Completed / Cancelled / Dead` 后才解除 barrier；
- 不同 Timeline 可以独立、并行推进。

## Rust workspace

```text
Loom
├── crates/
│   ├── loom-core/        # World Language: stable world mechanisms
│   ├── loom-protocol/    # Internal Execution Language: untrusted proposals
│   ├── loom-api/         # Public Consumption Language: one Loom API
│   ├── loom-capability/  # semantic extension API/SPI
│   ├── loom-agency/      # agent context/cognition extension API/SPI
│   ├── loom-runtime/     # execution + validation + logical commit + scheduler authority
│   ├── loom-storage/     # persistence adapter implementing Runtime-owned ports
│   └── loom-boundary/    # HTTP/SSE/WebSocket adapter over loom-api
├── apps/                 # composition roots and Loom consumers
├── tools/                # repository architecture/verification tooling
└── docs/
```

这些 crate 是**代码责任与依赖边界**，不是微服务边界。第一阶段保持单体 workspace，不为了未来场景提前拆服务。

## Dependency and public exposure rule

Loom 明确区分：

```text
semantic ownership
runtime call flow
Cargo dependency direction
authority / persistence domains
```

它们不是同一张图。

最核心的工程规则：

> **Core describes what a World is. Protocol describes execution proposals. API describes how Loom is consumed. Runtime decides what becomes reality.**

> **Extension defines semantics; Loom owns exposure.**

Capability 可以注册 `finance.transfer`、`employment.contract` 等语义，但不能自行注册 HTTP route、CLI command、GPUI engine endpoint 或 SDK service。HTTP、GPUI、CLI、SDK 等所有消费者统一通过 `loom-api` 使用 Loom。

Global Capability Registry 只能表示 installed software；Runtime 对 target World 的 Action、Work、Reaction、subresolution、semantic retrieval 与 World-scoped discovery 都必须再检查 World Runtime Binding。

Storage 可以实现 Work persistence、locking 和 `FOR UPDATE SKIP LOCKED` 等技术，但不能用数据库查询顺序重新定义 Timeline 的 logical next Work。

CI 会在 Rust 编译测试前执行 `tools/check_architecture.py`，对 workspace dependency allowlist 和明确的基础设施泄漏进行检查。架构违例属于 build failure，不是 warning。

## UI direction

官方 Loom UI 优先采用 **GPUI**，目标是在 Application 层共享 Native 与 Web/WASM UI 代码。GPUI 当前 Web backend 仍在快速演进，因此 UI 依赖会与 Engine contracts 完全隔离，并在正式接入时固定经过验证的 Zed/GPUI revision。

Studio 是 `loom-api` 的消费者，不直接依赖 Capability、Storage 或 Runtime 内部实现。

## Current status

**Loom v0 architecture is frozen.**

冻结内容至少包括：

```text
World Runtime Binding ownership
Installed vs World-enabled Capability semantics
explicit World Time progression
Timeline Logical Commit authority
semantic Work due-ness vs operational claimability
same-Timeline deterministic Durable Work ordering
head-of-line / due-work quiescence barrier
Execution Session vs Runtime Revision / exact implementation binding
Replay / Fork reconstruction domains
Capability host nondeterminism boundaries
Cargo dependency / authority placement rules
```

当前**不应直接继续旧 Roadmap 的代码实现**。

下一阶段是：

```text
Frozen Architecture
        ↓
Rebuild V0 implementation order
        ↓
Rebuild Issues / docs/tasks
        ↓
Resume implementation
```

旧 Issue/Task 如果与冻结架构冲突，以架构文档为准；应重做计划，而不是让架构迁就旧实现。
