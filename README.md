# Loom

> **Loom lets you create worlds that keep living.**

Loom 是一个用于构建、运行和扩展**持续演化智能世界**的开放引擎。

当前仓库已经进入独立实现阶段：Loom 不再以 MiroFish 的工程结构为基础，也不追求对其实现兼容。MiroFish 只作为历史源码与设计参考保留在 Git 历史/上游仓库中；当前工作树从 Loom 自己的架构重新开始。

## Architecture first

Loom 的权威设计来自：

- [`docs/vision.md`](docs/vision.md) — 项目愿景
- [`docs/principles.md`](docs/principles.md) — 跨领域硬原则
- [`docs/architecture/core.md`](docs/architecture/core.md) — Core v0 Conceptual Closure
- [`docs/architecture/layers.md`](docs/architecture/layers.md) — 产品/世界语义层级
- [`docs/architecture/evolution.md`](docs/architecture/evolution.md) — World Evolution 与 Runtime Change
- [`docs/architecture/implementation.md`](docs/architecture/implementation.md) — Loom v0 技术基线、依赖与数据权威
- [`docs/architecture/runtime-contracts.md`](docs/architecture/runtime-contracts.md) — Runtime / Capability / Effect / Durable Work 的详细实现契约与注释规范
- [`docs/architecture/governance.md`](docs/architecture/governance.md) — **强制 Rust 依赖方向、统一 Loom API 暴露与架构变更规则**

`runtime-contracts.md` 是 Core/Protocol/Runtime/Capability 公共抽象的直接语义依据；`governance.md` 是后续所有开发必须遵守的 Rust 物理依赖与公开能力治理规范。根目录 [`AGENTS.md`](AGENTS.md) 提供开发者/编码 Agent 的最小执行守则。

代码中的公开抽象必须使用 Rust doc comments 记录其意义、所有权、Truth domain、权限、禁止事项、持久化与一致性规则，不能要求维护者通过聊天记录猜测设计意图。

## Rust workspace

```text
Loom
├── crates/
│   ├── loom-core/        # World Language: stable world mechanisms
│   ├── loom-protocol/    # Internal Execution Language: untrusted proposals
│   ├── loom-api/         # Public Consumption Language: one Loom API
│   ├── loom-capability/  # semantic extension API/SPI
│   ├── loom-agency/      # agent context/cognition extension API/SPI
│   ├── loom-runtime/     # execution + validation + commit authority
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
```

三者不是同一张图。

最核心的工程规则：

> **Core describes what a World is. Protocol describes execution proposals. API describes how Loom is consumed. Runtime decides what becomes reality.**

> **Extension defines semantics; Loom owns exposure.**

Capability 可以注册 `finance.transfer`、`employment.contract` 等语义，但不能自行注册 HTTP route、CLI command、GPUI engine endpoint 或 SDK service。HTTP、GPUI、CLI、SDK 等所有消费者统一通过 `loom-api` 使用 Loom。

CI 会在 Rust 编译测试前执行 `tools/check_architecture.py`，对 workspace dependency allowlist 和明确的基础设施泄漏进行检查。架构违例属于 build failure，不是 warning。

## UI direction

官方 Loom UI 优先采用 **GPUI**，目标是在 Application 层共享 Native 与 Web/WASM UI 代码。GPUI 当前 Web backend 仍在快速演进，因此 UI 依赖会与 Engine contracts 完全隔离，并在正式接入时固定经过验证的 Zed/GPUI revision。

Studio 是 `loom-api` 的消费者，不直接依赖 Capability、Storage 或 Runtime 内部实现。

## Current status

**Core v0 conceptual boundary is frozen by default.**

Runtime contracts、Rust dependency governance 与统一 Loom API 暴露原则已经形成规范。当前阶段的目标不是移植旧代码，而是按这些 contract 让一个最小 Loom World 第一次真正运行起来。
