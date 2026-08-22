# Loom

> **Loom lets you create worlds that keep living.**

Loom 是一个用于构建、运行和扩展**持续演化智能世界**的开放引擎。

Loom 不以 MiroFish 的工程结构为基础，也不追求对其实现兼容。MiroFish 只作为历史源码与设计参考保留在 Git 历史/上游仓库中；当前工作树从 Loom 自己的架构重新开始。

## Architecture first

先读 [`docs/architecture/README.md`](docs/architecture/README.md)。它是 Loom v0 的 **document authority map**，定义每个主题的 canonical source、冲突裁决顺序、accepted Amendments 与当前 deferred decisions。

关键文档：

- [`docs/architecture/README.md`](docs/architecture/README.md) — document authority / precedence / amendment index
- [`docs/architecture/glossary.md`](docs/architecture/glossary.md) — canonical terminology
- [`docs/vision.md`](docs/vision.md) — 项目愿景
- [`docs/principles.md`](docs/principles.md) — cross-cutting philosophy，不再维护第二套编号规范
- [`docs/architecture/core.md`](docs/architecture/core.md) — Core conceptual closure
- [`docs/architecture/layers.md`](docs/architecture/layers.md) — 五层语义模型
- [`docs/architecture/world-runtime.md`](docs/architecture/world-runtime.md) — frozen World Runtime baseline
- [`docs/architecture/runtime-contracts.md`](docs/architecture/runtime-contracts.md) — detailed Runtime/Capability execution contract
- [`docs/architecture/evolution.md`](docs/architecture/evolution.md) — software/world evolution
- [`docs/architecture/governance.md`](docs/architecture/governance.md) — Cargo DAG / public exposure / authority placement
- [`docs/architecture/implementation.md`](docs/architecture/implementation.md) — technical realization baseline
- [`docs/architecture/amendments/0001-runtime-liveness-and-boundaries.md`](docs/architecture/amendments/0001-runtime-liveness-and-boundaries.md) — accepted runtime liveness/boundary amendment

建议阅读顺序：

```text
architecture/README + glossary
        ↓
vision + principles
        ↓
core + layers
        ↓
world-runtime
        ↓
accepted amendments
        ↓
runtime-contracts + evolution
        ↓
implementation + governance
```

`AGENTS.md` 是开发执行入口，不是另一份架构规范；遇到冲突必须回到 Architecture Index 指向的 canonical document。

## Core runtime distinctions

Loom v0 保持以下核心分离：

```text
Installed Capability
= platform software availability

World Runtime Binding
= one World's semantic enablement / compatibility contract

Execution Assembly
= exact software implementations pinned for one root Session
```

以及：

```text
World History
= committed Events + frozen Effects

Materialized World State
= Entity / Relationship / Facets

Timeline Logical State
= World Time / logical Work / logical ordering / TimelineVersion / ancestry

Platform Operational State
= lease / fence / retry / worker bookkeeping

Execution Provenance
= Runtime Revision / Session / exact implementation / read/call evidence
```

两个核心 mutation law：

> **No semantic World State mutation without a committed Event.**
>
> **No Timeline logical-state mutation without a Runtime-owned Logical Commit.**

World Time 是显式 Timeline logical state；PlatformClock、Event timestamp、retry/backoff 都不能隐式推动它。

## Amendment 0001 closure

冻结 baseline 后的正式审查发现了几个 scheduler/boundary liveness 出口缺口。Amendment 0001 已把它们纳入 v0 contract：

```text
bounded Runtime FailurePolicy
same-World-Time Chronology Budget
Runtime-owned Scheduler / Timeline Driver
single logical authority with multi-worker CAS/fencing
SKIP LOCKED only across independent Timeline heads
Runtime-stamped Event occurred_at
Ingress envelope -> normal Action authority path
World Template -> Runtime-owned ValidatedWorldBirthPlan
Intent / Trigger / Reaction / Actor / Agent terminology reconciliation
```

特别地：

- automatic technical retry 必须有界；terminal `Dead/Cancelled` 必须经 Logical Commit；
- 同一 WorldInstant 的 Immediate/Reaction 链达到 chronology budget 后停止自动推进，但**不能**借此越过 due Work 推进 World Time；
- `SKIP LOCKED` 可以帮助 worker 分配不同 Timeline 的 head，不能在同一 Timeline 内跳过 logical head；
- Ingress 是可靠 external envelope，不再形成第二套 Capability handler hierarchy；
- v0 `ProposedEvent` 不拥有选择 occurrence World Time 的 authority，Runtime 使用 pinned World Time stamp committed Event。

## Rust workspace

```text
Loom
├── crates/
│   ├── loom-core/        # World Language
│   ├── loom-protocol/    # Internal Execution Language
│   ├── loom-api/         # Public Consumption Language
│   ├── loom-capability/  # semantic extension API/SPI
│   ├── loom-agency/      # cognition/decision contracts
│   ├── loom-runtime/     # execution + validation + logical commit + scheduler authority
│   ├── loom-storage/     # persistence adapter implementing Runtime-owned ports
│   └── loom-boundary/    # transport adapter over loom-api
├── apps/                 # composition roots and Loom consumers
├── tools/                # architecture/verification tooling
└── docs/
```

这些 crate 是代码责任与依赖边界，不是微服务边界。v0 保持单体 Rust workspace。

最核心的工程规则仍然是：

> **Core describes what a World is. Protocol describes execution proposals. API describes how Loom is consumed. Runtime decides what becomes reality.**

> **Extension defines semantics; Loom owns exposure.**

完整 Cargo dependency/public exposure/authority placement 规则只以 `docs/architecture/governance.md` 为准，不在 README 再维护一份 allowlist。

## Current status

**Loom v0 architecture baseline + accepted Amendment 0001 are closed for re-planning.**

当前仍然不应直接继续旧 Roadmap 的代码实现。

下一阶段：

```text
Frozen baseline + accepted Amendments
        ↓
Rebuild V0 implementation order
        ↓
Rebuild Issues / docs/tasks
        ↓
Resume implementation
```

旧 Issues/tasks 只是历史计划输入；如果与当前 architecture authority map 冲突，必须重做计划，而不是让架构迁就旧实现。
