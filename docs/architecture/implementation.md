# Loom Rust Implementation Boundary

> Status: initial technical foundation after Core v0 conceptual closure.

本文只定义第一阶段 Rust 工程的责任边界，不提前决定尚未被真实实现证明需要的类、trait、数据库 Schema 或服务拆分。

## 1. Implementation principle

> **Implement Loom from the Loom architecture; do not translate MiroFish module-by-module.**

MiroFish 的旧 Python/Vue 实现不再作为 Loom 的工程骨架。需要参考某个具体算法或产品交互时，可以查看 Git 历史或上游实现，但 Loom 不为旧接口、旧流程或旧数据模型保持兼容。

## 2. Workspace ownership

```text
crates/loom-core
    World primitives, identity, timeline/state/history contracts and hard invariants

crates/loom-runtime
    execution sessions, durable work, world time, scheduling, resolution and commit authority

crates/loom-capability
    capability registration/binding/invocation and semantic extension contracts

crates/loom-agency
    agent-local view/context, decision contracts and cognitive executor boundary

crates/loom-boundary
    external ingress and committed-world feedback/output boundary

crates/loom-storage
    persistence implementations hidden behind Core/Runtime contracts

apps/
    user-facing Applications; not part of Core
```

这些边界可以随着真实实现证据调整，但领域语义不得反向进入 Core。

## 3. Dependency direction

总体原则：

```text
Applications / Adapters
        ↓
Agency / Boundary / Capability
        ↓
Runtime
        ↓
Core contracts

Storage implements required persistence contracts
without becoming World semantics.
```

具体 crate 依赖在第一批核心类型与 Commit Transaction 设计完成后再确定，不为了画出漂亮依赖图提前制造 trait。

## 4. GPUI direction

Loom 官方 UI 优先评估 GPUI 作为统一 Rust Application UI。

Zed 当前 main 已包含 `gpui_web`，`gpui_platform` 在 `wasm` target 下创建 Web platform，部分官方 GPUI examples 同时提供 native entrypoint 与 `wasm_bindgen` Web entrypoint。因此 Native + Browser/WASM 已经存在基础实现。

但 GPUI 仍处于快速演进阶段，published crate 与 main 的能力可能不同。因此：

1. GPUI 只存在于 `apps/` Application 层；
2. Core/Runtime 永远不依赖 GPUI；
3. 正式接入 Web backend 前固定经过验证的 upstream revision；
4. 不因为 UI 框架变化修改 World/Core contracts；
5. Native 与 Web 优先共享 UI/state composition，但允许平台适配代码存在。

参考：
- https://github.com/zed-industries/zed/tree/main/crates/gpui
- https://github.com/zed-industries/zed/tree/main/crates/gpui_platform
- https://github.com/zed-industries/zed/tree/main/crates/gpui_web

## 5. First implementation milestone

第一阶段只证明 World Runtime 闭环：

```text
Create World / Timeline
        ↓
create minimal identity/state
        ↓
submit Work / Intent
        ↓
Resolve
        ↓
Commit Event + Effects
        ↓
materialize State
        ↓
schedule Durable Work
        ↓
pause / reload / resume
```

先不引入完整社会、经济、信息、记忆或人类心理 Capability；也不以 LLM 是否接通作为 Core 是否成立的判断标准。

## 6. Repository rule

当前工作树只保留 Loom 自己的实现与文档。旧 MiroFish 工程代码不设置 `legacy/` 墓地目录；需要追溯时使用 Git 历史。
