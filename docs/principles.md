# Loom Design Principles

> Status: stable cross-cutting laws.
>
> 本文只保留跨多个架构主题都成立的硬原则；详细结构分别以 `docs/architecture/core.md`、`layers.md`、`evolution.md` 为准，不在这里重复完整模型。

## Core boundary

1. **Loom Core is a world runtime, not a domain-specific simulator.**
2. Core 决定世界怎样存在和运行；Capability 定义语义；Application 定义用途和体验。
3. 一个概念“很重要”不代表它必须进入 Core；能通过现有 Core + Capability 表达的能力默认留在 Capability。
4. Core 默认冻结；新增 Kernel 概念必须重新通过 Core Admission Review。
5. Extensibility 本身属于 Core，具体领域语义不属于 Core。

## World, Timeline, identity

6. World 是长期存在的世界身份和运行边界，不是一次请求、simulation job 或 report。
7. Timeline 是 World 中的一条权威历史分支；每条 Timeline 只有一份权威 Event Ledger。
8. Entity/Relationship 的 Trajectory 是 Timeline 的局部投影，不是另一套权威历史。
9. **Identity belongs to World; mutable State belongs to Timeline.**
10. Identity 必须由稳定、唯一、不可复用、与名称和可变状态无关的内部 ID 建立。
11. **Names describe identity; they do not create it.**
12. Fork 延续 Fork Point 已存在的 World Identity，分离之后的 State、Pending Work 和未来结果。

## History and state

13. **No mutation without a committed Event.**
14. Intent 是尝试；Event 是已发生事实；Effect 是已解析的状态变化，三者严格分离。
15. Event Ledger append-only；已经提交的历史不能被静默重写。
16. Current State 是 Timeline 当前现实的 materialized projection。
17. Commit 后的 Event 保存最终 resolved outcome / Effects；Replay 不重新随机、不重新调用模型决定历史。
18. Direct Effect 与 downstream Reaction 分离；后续影响形成新的 Work / Intent / Event。
19. World Event Ledger 与技术日志、Runtime Audit、Platform Change History 分离。

## Past, present, future

20. **Event records the determined past; State represents current reality; Durable Work represents unresolved future execution.**
21. **A scheduled future is not a future fact.** Future Work 在真正执行时依据当时最新 Timeline State 判断结果。
22. Durable Work 必须可持久化、可恢复、可取消/替代、可安全重试，并保持 Timeline isolation。
23. 跨时间多阶段 Process 默认由 Capability 使用 State + Event + Durable Work + Trigger 组合，不进入 Core Primitive。

## Agency and cognition

24. **World Truth ≠ Agent View.** Agent cognition 不默认读取 omniscient World State。
25. **Context is budgeted attention.** Visibility / knowledge eligibility 先于 relevance。
26. Agent 可以拥有不完整、过时甚至错误的 local representation。
27. Core 保证 persistent agent-local state 与 context retrieval boundary，但不强制人类 Memory / Goal / Emotion / Personality 模型。
28. **Agent persists; compute is on demand.**
29. LLM 不等于 Agent。Core 可以提供可配置 LLM Executor，但它只是 Cognitive Executor 的一种实现。
30. Cognitive Provider 只能产生受约束的 Decision / Intent，不能直接修改 State 或 Commit Event。
31. Core 不规定固定的 Fast Path → Cognitive Path；Execution Policy / Strategy 必须可替换、可组合。

## Action, rule and runtime authority

32. **Can I? ≠ Will I?** Feasibility 与 Decision 分离。
33. Actual Affordance 与 Perceived Affordance 分离；Agent 可以基于错误认知尝试并失败。
34. Loom 区分 impossibility、access/authority/permission、law/policy/norm 和 enforcement/reaction。
35. Norm violation 不等于 Commit failure；违法、违规或失礼仍可能成为真实 Event。
36. Hard Runtime Invariant 应尽可能少，只保护 identity、Timeline、state schema、atomicity、referential integrity 等运行一致性。
37. 只有 Runtime 可以 Commit World Event；Timeline Commit 是 State mutation 的唯一线性化点。
38. Capability 可以解释世界并提出 Evaluation / Proposal / Work，但不能接管 Runtime 主循环或直接修改权威世界状态。

## Runtime boundaries and uncertainty

39. 外部输入必须通过 Ingress 进入 Runtime；Ingress accepted 不等于输入内容已经成为 World Truth。
40. Feedback / World Change Feed 是只读观察边界；Loom Core 不直接执行现实世界副作用。
41. 外部根据 Feedback 再次影响 World 时，必须重新通过 Ingress。
42. **Anything that can influence World Truth must enter through an explicit Core boundary.**
43. World-affecting time、randomness、external input、cognition 和 registered domain logic 必须有明确执行来源；Capability 不应隐藏系统时间、随机数、模型调用或外部查询来改变 Resolution。
44. Historical replay 应用 committed history；counterfactual re-simulation 从共享历史重新计算另一种未来。

## Evolution and software change

45. **Worlds evolve; software upgrades. Never confuse the two.**
46. 世界规则、制度、技术和能力变化属于 World History，并按其 effective time 影响未来，不重写过去。
47. Template 是 World 的出生配方，不持续同步或控制已创建 World。
48. World 不执行“upgrade to Runtime Revision”；新启动的 Execution Session 自然运行在当前已激活引擎上。
49. 已开始的 Execution Session 固定其 Runtime Revision 到结束；尚未开始的 Durable Work 在真正执行时使用当时当前引擎。
50. Bug Fix 可以改变之后的新执行行为，但不能静默重算 committed Event 或修写既有 State consequences。
51. 平台软件变化记录在独立 Runtime Change Ledger；Execution Provenance 允许人类审计某个 Event 当时使用的 Runtime/Capability/Executor 环境。
52. Runtime Change / Execution Provenance 默认不可进入 Agent Context，也不是 World Event。

## Final admission law

> **如果没有某个概念，持续 World Runtime 仍然能够闭环，并且该能力可以由 Capability 组合表达，那么它不应进入 Loom Core。**