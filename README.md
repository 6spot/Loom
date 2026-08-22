# Loom

> **Loom lets you create worlds that keep living.**

Loom 是一个用于构建、运行和扩展**持续演化智能世界**的开放引擎。

Loom 不以 MiroFish 的工程结构为基础，也不追求对其实现兼容。MiroFish 只作为历史源码与设计参考保留在 Git 历史/上游仓库中；当前工作树从 Loom 自己的架构重新开始。

## Architecture first

Loom 的权威设计来自：

- [`docs/vision.md`](docs/vision.md) — 项目愿景与完整世界运行图景
- [`docs/principles.md`](docs/principles.md) — 跨领域硬原则
- [`docs/architecture/core.md`](docs/architecture/core.md) — Core v0 Conceptual Closure
- [`docs/architecture/layers.md`](docs/architecture/layers.md) — 产品/世界五层语义层级
- [`docs/architecture/world-runtime.md`](docs/architecture/world-runtime.md) — **World Runtime Binding、World Time、Logical Commit、Execution Session 的闭环契约**
- [`docs/architecture/evolution.md`](docs/architecture/evolution.md) — World Evolution、World Binding 与 Runtime Change
- [`docs/architecture/runtime-contracts.md`](docs/architecture/runtime-contracts.md) — Runtime / Capability / Effect / Durable Work 的详细执行契约与注释规范
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

`world-runtime.md` 是当前架构闭环的中心文档；`runtime-contracts.md` 是 Core/Protocol/Runtime/Capability 公共抽象的直接执行语义依据；`governance.md` 是所有开发必须遵守的 Rust 物理依赖、authority placement 与公开能力治理规范。根目录 [`AGENTS.md`](AGENTS.md) 提供开发者/编码 Agent 的执行守则。

代码中的公开抽象必须使用 Rust doc comments 记录其意义、所有权、Truth/authority domain、权限、禁止事项、持久化与一致性规则，不能要求维护者通过聊天记录猜测设计意图。

## Core runtime distinctions

当前架构明确区分：

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
= World Time / logical Work / TimelineVersion / ancestry

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

## Rust workspace

```text
Loom
├── crates/
│   ├── loom-core/        # World Language: stable world mechanisms
│   ├── loom-protocol/    # Internal Execution Language: untrusted proposals
│   ├── loom-api/         # Public Consumption Language: one Loom API
│   ├── loom-capability/  # semantic extension API/SPI
│   ├── loom-agency/      # agent context/cognition extension API/SPI
│   ├── loom-runtime/     # execution + validation + logical commit authority
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

CI 会在 Rust 编译测试前执行 `tools/check_architecture.py`，对 workspace dependency allowlist 和明确的基础设施泄漏进行检查。架构违例属于 build failure，不是 warning。

## UI direction

官方 Loom UI 优先采用 **GPUI**，目标是在 Application 层共享 Native 与 Web/WASM UI 代码。GPUI 当前 Web backend 仍在快速演进，因此 UI 依赖会与 Engine contracts 完全隔离，并在正式接入时固定经过验证的 Zed/GPUI revision。

Studio 是 `loom-api` 的消费者，不直接依赖 Capability、Storage 或 Runtime 内部实现。

## Current status

**Implementation expansion is intentionally paused for architecture closure review.**

当前 review 的目标不是继续实现旧 Roadmap，而是先确认以下架构闭环完全一致：

```text
World Runtime Binding ownership
explicit World Time progression
Timeline Logical Commit authority
Installed vs World-enabled Capability semantics
Execution Session vs Runtime Revision / exact implementation binding
Replay / Fork reconstruction domains
Capability host nondeterminism boundaries
```

在这组架构文档通过人工确认之前，不应继续扩展代码，也不应按旧 Milestone/Issue 顺序惯性推进。

确认完成后，下一步是**重新规划实现顺序与 Issues**，而不是直接从旧 Roadmap 续跑。