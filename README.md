# Loom

> **Loom lets you create worlds that keep living.**

Loom 是一个用于构建、运行和扩展**持续演化智能世界**的开放引擎。

当前仓库已经进入独立实现阶段：Loom 不再以 MiroFish 的工程结构为基础，也不追求对其实现兼容。MiroFish 只作为历史源码与设计参考保留在 Git 历史/上游仓库中；当前工作树从 Loom 自己的架构重新开始。

## Architecture first

Loom 的权威设计来自：

- [`docs/vision.md`](docs/vision.md) — 项目愿景
- [`docs/principles.md`](docs/principles.md) — 跨领域硬原则
- [`docs/architecture/core.md`](docs/architecture/core.md) — Core v0 Conceptual Closure
- [`docs/architecture/layers.md`](docs/architecture/layers.md) — 五层所有权边界
- [`docs/architecture/evolution.md`](docs/architecture/evolution.md) — World Evolution 与 Runtime Change
- [`docs/architecture/implementation.md`](docs/architecture/implementation.md) — Rust 实现边界

## Rust workspace

```text
Loom
├── crates/
│   ├── loom-core/        # World primitives and invariant contracts
│   ├── loom-runtime/     # execution, durable work, scheduling, commit authority
│   ├── loom-capability/  # capability host and semantic extension contracts
│   ├── loom-agency/      # agent-local context and cognitive execution contracts
│   ├── loom-boundary/    # ingress and feedback boundaries
│   └── loom-storage/     # persistence implementations behind Core contracts
├── apps/                 # Loom applications; official UI will live here
└── docs/
```

这些 crate 是**代码责任边界**，不是微服务边界。第一阶段保持单体 workspace，不为了未来场景提前拆服务。

## UI direction

官方 Loom UI 优先采用 **GPUI**，目标是在 Application 层共享 Native 与 Web/WASM UI 代码。GPUI 当前 Web backend 仍在快速演进，因此 UI 依赖会与 Core 完全隔离，并在正式接入时固定经过验证的 Zed/GPUI revision。

Core、Runtime、Capability 与 Storage 不依赖任何 UI 框架。

## Current status

**Core v0 conceptual boundary is frozen by default.**

当前阶段的目标不是移植旧代码，而是让一个最小 Loom World 第一次按新的 Core 契约真正运行起来。
