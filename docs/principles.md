# Loom Design Principles

> Status: stable cross-cutting laws after World Runtime Closure review.
>
> 本文只保留跨多个架构主题都成立的硬原则；详细结构分别以 `docs/architecture/core.md`、`layers.md`、`world-runtime.md`、`evolution.md` 为准，不在这里重复完整模型。

## Core boundary

1. **Loom Core is a world runtime, not a domain-specific simulator.**
2. Core 决定世界怎样存在和运行；Capability 定义语义；Application 定义用途和体验。
3. 一个概念“很重要”不代表它必须进入 Core；能通过现有 Core + Capability 表达的能力默认留在 Capability。
4. Core 默认冻结；新增 Kernel 概念必须重新通过 Core Admission Review。
5. Extensibility 本身属于 Core，具体领域语义不属于 Core。

## World, Timeline, identity and binding

6. World 是长期存在的世界身份和运行边界，不是一次请求、simulation job 或 report。
7. Timeline 是 World 中的一条权威历史分支；每条 Timeline 只有一份权威 Event Ledger。
8. Entity/Relationship 的 Trajectory 是 Timeline 的局部投影，不是另一套权威历史。
9. **Identity belongs to World; mutable semantic State belongs to Timeline.**
10. Identity 必须由稳定、唯一、不可复用、与名称和可变状态无关的内部 ID 建立。
11. **Names describe identity; they do not create it.**
12. Fork 延续 Fork Point 已存在的 World Identity，分离之后的 State、World Time、Pending Work 和未来结果。
13. **Installed Capability != enabled Capability for a World.** Runtime 中存在某个实现，不代表每个 World 都允许使用它。
14. World 持有持久的 **World Runtime Binding**；它表达允许的 Capability semantic requirements/configuration，并由该 World 的所有 Timeline 共享。
15. World Runtime Binding 不永久 pin 某个 Runtime Revision 或 exact Capability implementation；exact software binding 属于 Execution Session provenance。
16. v0 World Runtime Binding 创建后不可静默修改；世界中的法律、技术、规则、能力可用性等演化默认通过 Event + State 表达，而不是热插拔 software Capability。

## History, state and logical timeline state

17. **No semantic World State mutation without a committed Event.** Entity / Relationship / Facet 的语义变化必须由 committed Event 的 frozen Effects 解释。
18. Intent 是尝试；Event 是已发生事实；Effect 是已解析的状态变化，三者严格分离。
19. Event Ledger append-only；已经提交的历史不能被静默重写。
20. Current materialized World State 是 Timeline 当前现实的 projection。
21. Commit 后的 Event 保存最终 resolved outcome / Effects；Replay 不重新随机、不重新调用模型决定历史。
22. Direct Effect 与 downstream Reaction 分离；后续影响形成新的 Work / Intent / Event。
23. World Event Ledger 与 Timeline Logical Journal、技术日志、Runtime Audit、Platform Change History 分离。
24. **No Timeline logical-state mutation without a Runtime-owned logical commit.** World Time、logical Work 等可重建 Timeline 状态不需要伪造领域 Event，但必须进入明确的 logical commit/history。
25. Platform lease/fence/retry/backoff 是 operational state；它不属于 World History 或 Timeline logical history，也不推进 TimelineVersion。

## Past, present, future and World Time

26. **Event records the determined past; materialized State represents current reality; Durable Work represents unresolved future execution.**
27. **A scheduled future is not a future fact.** Future Work 在真正执行时依据当时最新 Timeline State 判断结果。
28. Durable Work 必须可持久化、可恢复、可取消/替代、可安全重试，并保持 Timeline isolation。
29. 跨时间多阶段 Process 默认由 Capability 使用 State + Event + Durable Work + Trigger 组合，不进入 Core Primitive。
30. **World Time is explicit Timeline logical state, not a derivation from Event timestamps.**
31. World Time 只能单调前进，并且每次真实推进都必须通过 Runtime authority 的显式 logical transition 持久化。
32. **Platform Time never implicitly advances World Time.** wall clock、retry backoff、lease expiry、database `NOW()` 都不能偷偷改变世界语义时间。
33. Event 在 pinned World Time 上发生；Event timestamp 不能作为“顺便把 clock 推到未来”的机制。
34. Replay 必须从 logical history 恢复 World Time，不能用 `max(event.occurred_at)` 或 Platform timestamp 猜测。

## Agency and cognition

35. **World Truth ≠ Agent View.** Agent cognition 不默认读取 omniscient World State。
36. **Context is budgeted attention.** Visibility / knowledge eligibility 先于 relevance。
37. Agent 可以拥有不完整、过时甚至错误的 local representation。
38. Core 保证 persistent agent-local state 与 context retrieval boundary，但不强制人类 Memory / Goal / Emotion / Personality 模型。
39. **Agent persists; compute is on demand.**
40. LLM 不等于 Agent。Core 可以支持可配置 Cognitive Executor，但它只是 cognition implementation 的一种。
41. Cognitive Executor 只能产生受约束的 Decision / Intent；标准 v0 路径通过 `Decision::Act(ActionInvocation)` 重新进入正常 Action authority，不能直接修改 State 或 Commit Event。
42. Core 不规定固定的 Fast Path → Cognitive Path；Execution Policy / Strategy 必须可替换、可组合。

## Action, rule and runtime authority

43. **Can I? ≠ Will I?** Feasibility 与 Decision 分离。
44. Actual Affordance 与 Perceived Affordance 分离；Agent 可以基于错误认知尝试并失败。
45. Loom 区分 impossibility、access/authority/permission、law/policy/norm 和 enforcement/reaction。
46. Norm violation 不等于 Commit failure；违法、违规或失礼仍可能成为真实 Event。
47. Hard Runtime Invariant 应尽可能少，只保护 identity、Timeline、state schema、atomicity、referential integrity、binding/time consistency 等运行一致性。
48. 只有 Runtime 可以 Commit World Event；Timeline Commit 是 semantic State mutation 的唯一线性化点。
49. Capability 可以解释世界并提出 Evaluation / Proposal / Work，但不能接管 Runtime 主循环或直接修改权威世界状态。
50. Runtime 对 Action、WorkHandler、Reaction、subresolution、semantic index/catalog 等 World-scoped semantic entry 都必须强制 World Runtime Binding；global registry presence 不是授权。

## Runtime boundaries and uncertainty

51. 外部输入必须通过 Ingress 进入 Runtime；Ingress accepted 不等于输入内容已经成为 World Truth。
52. Feedback / World Change Feed 是只读观察边界；Loom Core 不直接执行现实世界副作用。
53. 外部根据 Feedback 再次影响 World 时，必须重新通过 Ingress。
54. **Anything that can influence World Truth must enter through an explicit Runtime/Core boundary.**
55. World-affecting time、randomness、external input、cognition 和 registered domain logic 必须有明确执行来源；Capability 不应隐藏系统时间、随机数、模型调用或外部查询来改变 Resolution。
56. Capability 读取的是 pinned World Time，而不是 PlatformClock；需要未来重评估时应 Schedule Work，而不是 sleep/wall-clock waiting。
57. Entropy 必须通过 Runtime-controlled request/sample boundary，并进入 Execution Provenance；Replay 永不重新采样。
58. Historical replay 应用 committed history；counterfactual re-simulation 从共享历史重新计算另一种未来。

## Execution sessions and software evolution

59. 每个可能形成 World Truth 的 root execution 都必须有明确 Execution Session，并在开始时 pin 一套 Execution Assembly。
60. Execution Assembly 至少确定 target World/Timeline、pinned TimelineVersion、World Runtime Binding、active Runtime Revision 和 exact compatible Capability implementations。
61. 一个 Session 开始后不得中途切换 Runtime Revision 或 Capability implementation；subresolution 继承同一 execution assembly。
62. **Worlds evolve; software upgrades. Never confuse the two.**
63. 世界规则、制度、技术和领域能力变化属于 World History，并按其 effective time 影响未来，不重写过去。
64. Template 是 World 的出生配方，产生初始 Binding/State/Work，但不持续同步或控制已创建 World。
65. World 不执行“upgrade to Runtime Revision”；新启动的 compatible Execution Session 自然运行在当前已激活引擎上。
66. 尚未开始的 Durable Work 在真正执行时使用当时当前的 compatible execution assembly，而不是创建 Work 时的旧 binary。
67. Bug Fix 可以改变之后的新执行行为，但不能静默重算 committed Event 或修写既有 State consequences。
68. 平台软件变化记录在独立 Runtime Change Ledger；Execution Provenance 审计某个 Event 当时使用的 Runtime/Capability/Executor 环境。
69. Runtime Change / Execution Provenance 默认不可进入 Agent Context，也不是 World Event。
70. Exact Capability implementation version 属于 Execution Provenance；World Runtime Binding 只保存 semantic capability requirement/configuration，不把 World 永久钉在旧实现。

## Final admission law

> **如果没有某个概念，持续 World Runtime 仍然能够闭环，并且该能力可以由 Capability 组合表达，那么它不应进入 Loom Core。**
>
> **如果某个变化影响 semantic World State，它必须由 Event 解释；如果它只改变可重建的 Timeline execution/time/future state，它必须由 Runtime logical commit 解释；如果它只服务平台可靠性，它必须留在 operational state。**