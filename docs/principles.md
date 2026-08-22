# Loom Design Principles

> Status: **stable cross-cutting philosophy for Loom v0.**
>
> 本文不再维护另一套编号 Runtime 规范。具体语义、authority、scheduler、Cargo 依赖与公共暴露规则，以 [`docs/architecture/README.md`](architecture/README.md) 的 document authority map 为准。

## 1. World before use case

- **Loom Core is a world runtime, not a domain-specific simulator.**
- Core 定义跨领域仍成立的 World mechanism；Capability 定义语义；Application 定义用途与体验。
- 一个概念很重要，不代表它必须进入 Core。能由已有 Core + Capability 表达的能力默认留在 Capability。
- World 是持续 identity/runtime boundary，不是一次 request、simulation job 或 report。
- Timeline 是 World 的历史分支；Identity 与 branch-local mutable state 不应混为一谈。

## 2. Truth and authority are explicit

- **No semantic World State mutation without a committed Event.**
- **No Timeline logical-state mutation without a Runtime-owned Logical Commit.**
- World History、Materialized World State、Timeline Logical State、Platform Operational State 与 Execution Provenance 必须保持不同 authority domain。
- Event 记录已经确定的过去；Durable Work 表示尚未决定结果的未来执行义务。
- Platform reliability 可以延迟执行，但不能偷偷改写 World semantics、World Time 或 same-Timeline chronology。

## 3. Time is world semantics, not server time

- World Time 是 Timeline-local semantic coordinate，不是系统时钟、DB `NOW()` 或 Event timestamp 的推导结果。
- World Time 只能通过 Runtime authority 的显式 logical transition 前进。
- Source/platform/effective/historical timestamps 必须使用各自明确的 domain semantics，不能偷用 World clock。

## 4. Runtime owns execution authority

- Capability 可以解释世界、提出 Resolution、Schedule Work，但不能直接 Commit World Truth、改 Timeline logical state 或获得 Storage/Clock/Network/Commit authority。
- Storage 实现 Runtime-owned ports；它不因为持久化数据就获得 semantic authority。
- Application/Boundary 通过统一 `loom-api` 使用 Loom，不能建立 Capability-specific authority bypass。
- Runtime call flow、semantic ownership、Cargo dependency direction 与 persistence location 是不同的图。

## 5. Installed software is not World semantics

- **Installed Capability != enabled Capability for a World.**
- World Runtime Binding 表达 World 允许的 semantic capability requirements；Execution Assembly 表达某次 Session 实际 pin 的 exact implementations。
- **Worlds evolve; software upgrades. Never confuse the two.** Runtime Revision activation 不重写既有 World History。

## 6. Determined history is replayed, not recomputed

- Replay 应用 committed Event/Effects 与 Timeline logical history，不重新调用 current Resolver、Entropy、Cognition 或数据库偶然排序来猜历史。
- Fork 继承 fork-point 已确定的 World/Timeline logical past，并从那里产生 branch-local future。
- Execution Provenance 用于解释“软件当时怎样算出来”，不是 World replay authority。

## 7. Agency is constrained by World authority

- **World Truth ≠ Agent View.** Agent cognition 不默认读取 omniscient authoritative world state。
- LLM 不等于 Agent；Cognitive Executor 只是 Agency 的一种 implementation。
- Cognition 决定要尝试什么；Capability 决定尝试在当前世界意味着什么；Runtime 决定什么可以成为现实。
- `Intent` 可以是认知/Agency 概念，但 v0 不因此引入 generic Runtime `Intent` protocol type。

## 8. Future execution must remain live and auditable

- Durable Work 必须持久、可恢复、可取消/terminalize、可安全重试，并保持 Timeline isolation。
- Semantic due-ness 与 operational claimability 必须分离；平台 retry/lease/worker 状态不能改变 Work 在 World chronology 上是否已到期。
- Scheduler liveness 需要明确 failure exit 与 same-World-Time budget；它们的 authoritative contract 见 accepted Architecture Amendments。

## Final admission law

> **如果没有某个概念，持续 World Runtime 仍然能够闭环，并且该能力可以由 Capability 组合表达，那么它不应进入 Loom Core。**
>
> **如果某个变化影响 semantic World State，它必须由 Event 解释；如果它只改变可重建的 Timeline execution/time/future state，它必须由 Runtime Logical Commit 解释；如果它只服务平台可靠性，它必须留在 operational state。**
