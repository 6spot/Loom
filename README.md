# Loom

> **Loom lets you create worlds that keep living.**

Loom 是一个用于构建、运行和扩展**持续演化智能世界**的开放引擎。

Loom 不以 MiroFish 的工程结构为基础，也不追求对其实现兼容。MiroFish 只作为历史源码与设计参考保留在 Git 历史/上游仓库中；当前工作树从 Loom 自己的架构重新开始。

## Architecture first

先读 [`docs/architecture/README.md`](docs/architecture/README.md)。它是 Loom v0 的 **document authority map**，定义每个主题的 canonical source、冲突裁决顺序、reverse supersession table、accepted Amendments 与当前 deferred decisions。

关键文档：

- [`docs/architecture/README.md`](docs/architecture/README.md) — document authority / precedence / reverse supersession / amendment index
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
- [`docs/architecture/amendments/0001-runtime-liveness-and-boundaries.md`](docs/architecture/amendments/0001-runtime-liveness-and-boundaries.md) — runtime liveness/boundary closure
- [`docs/architecture/amendments/0002-supersession-and-authority-linkage.md`](docs/architecture/amendments/0002-supersession-and-authority-linkage.md) — exact supersession mapping / authority linkage cleanup

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
all accepted amendments
        ↓
runtime-contracts + evolution
        ↓
implementation + governance
```

冻结 baseline 仍保留其历史原文。**在把任何 baseline 章节转成实现任务之前，必须先查 Architecture Index 的 reverse supersession table。** `AGENTS.md` 是开发执行入口，不是另一份架构规范。

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
= World Time / logical Work / logical ordering
  / Chronology Budget consumption / TimelineVersion / ancestry

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

## Accepted amendment closure

Amendment 0001 + 0002 已把冻结后审查发现的 runtime/document closure 纳入当前 v0 contract：

```text
bounded Runtime FailurePolicy
same-World-Time Chronology Budget
Chronology Budget consumption = Timeline Logical State
Runtime-owned Scheduler / Timeline Driver
single logical authority with multi-worker CAS/fencing
SKIP LOCKED only across independent Timeline heads
one canonical Scheduler claim/admission checklist
Runtime-stamped Event occurred_at
Ingress envelope -> normal Action authority path
World Template -> Runtime-owned ValidatedWorldBirthPlan
Intent / Trigger / Reaction / Actor / Agent terminology reconciliation
exact baseline supersession mapping
current CI baseline = Ubuntu mandatory; macOS currently deferred
TimelineBlockedOnMissingImplementation observability
```

特别地：

- automatic technical retry 必须有界；terminal `Dead/Cancelled` 必须经 Logical Commit；
- 同一 WorldInstant 的 Immediate/Reaction 链达到 chronology budget 后停止自动推进，但**不能**借此越过 due Work 推进 World Time；
- chronology-budget consumption 与 logical Work completion 在同一个 Logical Commit 中记录/重建，不是 operational worker counter；
- `SKIP LOCKED` 可以帮助 worker 分配不同 Timeline 的 head，不能在同一 Timeline 内跳过 logical head；
- operational claimability/Admission 的完整条件只认 accepted Amendment 的 canonical checklist；
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

**Loom v0 frozen baseline + accepted Amendments 0001 and 0002 are closed for re-planning.**

当前仍然不应直接继续旧 Roadmap 的代码实现。

下一阶段：

```text
Frozen baseline + accepted Amendments
        ↓
Resolve supersession index
        ↓
Rebuild V0 implementation order
        ↓
Rebuild Issues / docs/tasks
        ↓
Resume implementation
```

旧 Issues/tasks 只是历史计划输入；如果与当前 architecture authority map / accepted Amendments 冲突，必须重做计划，而不是让架构迁就旧实现。
