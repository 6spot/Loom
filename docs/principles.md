# Loom Design Principles

> Status: confirmed architectural baseline.
>
> 本文记录 Loom 已确认的设计原则。它既包含 Core Laws，也包含对官方 Capability 的语义约束；某个概念“设计上重要”并不等于它必须属于 Kernel。具体架构归属以 `docs/architecture/core.md` 与 `docs/architecture/layers.md` 为准。

## 1. Core and architecture

1. Loom Core is a **world runtime**, not a domain-specific simulator.
2. Loom 使用五层边界：**Core -> Capability Module -> World Template -> World <- Application**。
3. Core 决定世界怎样存在和运行；Capability 决定世界会什么、意味着什么；Application 决定用户拿 World 做什么。
4. Core 的准入标准是：移除该概念后，持续 World Runtime 是否无法闭环；重要但非闭包必需的概念优先进入 Capability。
5. World Template 是创建 World 的出生配方，不持续控制或同步已创建 World。
6. Application ≠ World；一个 World 可以被多个 Application 观察和使用。
7. Extensibility 本身属于 Core；具体领域语义不属于 Core。

## 2. World, timeline, identity

8. World 是长期存在的世界身份和运行边界，不是一次请求、simulation job 或 report。
9. Timeline 是 World 中的一条权威历史分支；每条 Timeline 只有一份权威 Event Ledger。
10. Fork 创建新的历史分支，不重写原 Timeline。
11. **Identity belongs to World; mutable State belongs to Timeline.**
12. 同一个 World Entity 在不同 Timeline 上仍然是同一个 Identity，只是状态、关系、经历、认知和后续轨迹可以不同。
13. Identity 必须由稳定、唯一、不可复用、与名称和可变状态无关的内部 ID 建立。
14. **Names describe identity; they do not create it.** 名字、别名、职位、位置等不是身份本身。
15. Global Entity 是可选的跨 World 身份锚点；World Entity 是某个 World 内稳定身份；Timeline State 是某条历史上的可变状态。
16. Fork 时已经存在的 World Entity Identity 必然延续；Fork 后新产生的 Entity 默认由各分支历史独立创建，除非显式建立对应关系。
17. Entity、Actor、Agent 是 Runtime 结构角色，不是 `HUMAN / COMPANY / COUNTRY / MONSTER` 等领域类型。
18. Actor 表示行动归属主体；Agent 是拥有局部认知和自主决策能力的 Actor。

## 3. Timeline and trajectory

19. 个人、公司、国家等主体不各自拥有独立权威 Timeline。
20. Entity 在某条 World Timeline 上拥有自己的 **Trajectory**；Trajectory 是 World Ledger 的局部投影/索引，而不是第二套历史权威。
21. Relationship 也可以拥有自己的 Trajectory。
22. 同一个 Event 可以同时属于多个 Entity / Relationship Trajectory，因此不同主体的演化路径通过共享 Event 发生交集。
23. Objective Entity Trajectory 与 Agent Experienced History 分离：事实上发生过，不代表 Agent 当时知道、记住或正确理解。

## 4. Entity, relationship, state

24. Entity 的核心职责是稳定身份，不应承载巨大固定领域 Schema。
25. 领域状态通过可组合、版本化、可验证的 **State Facet** 附着到 Entity / Relationship 的 Timeline-local State 上。
26. State Facet 必须有正式 Definition / Schema / Validation / Version，不是自由 JSON 堆积。
27. Capability 定义 Facet 语义，Core 负责 persistence、revision、Timeline isolation、event-driven mutation、snapshot 和 projection 生命周期。
28. Entity 的领域能力和状态可以随 committed Event 动态增加、变化或结束，不依赖固定继承树。
29. Relationship 是独立 Core Primitive，不是 Entity Facet；它拥有唯一身份、参与者、角色、Timeline-local State 和生命周期。
30. Relationship 应支持 N-ary participant/role 模型，二元 edge 只是特例。
31. Core 不理解 friend / married / employed_by / owns 等具体 Relationship 语义。
32. Multiplex Relationship 是正常情况：相同 Entity 之间可以同时存在多种不同关系。

## 5. History and state change

33. **No mutation without a committed Event.**
34. Intent 是行动意图，Action Attempt 是一次尝试，Event 是已提交的历史事实，Effect 是确定性 State 变化；四者严格分离。
35. Runtime 是唯一 Commit Authority；Agent、Capability、Application、External Source 都不能直接修改 Timeline State。
36. Event Ledger append-only；已经提交的历史不得被静默改写。
37. Event 必须保存已解析 outcome 和 Effects；Replay 不重新随机、不重新调用模型决定已提交历史。
38. Nondeterminism may happen before commit; committed history is deterministic.
39. Current State 是高效运行所需的 materialized projection，不是历史本身。
40. Direct Effect 与 downstream Reaction 分离；后续影响通过新的 Work / Intent / Event 形成因果链。
41. 一个 Intent 可以产生 0..N Events；一个 Event 也可以由多个 Intent / Process 共同促成。
42. 失败尝试仍可能形成真实 Event；“未成功改变目标状态”不等于“什么都没有发生”。
43. User/Application Intervention 同样必须经过 Runtime -> Event -> Effect。
44. World Event Ledger 与 technical log / debug log 严格分离。

## 6. Time and runtime

45. World Time 与操作系统时间分离；External occurrence time、received time、effective/valid time、commit time/sequence 也应保持区别。
46. Ledger sequence 是 Timeline 的权威线性 Commit 顺序。
47. Loom Runtime 是 **event-driven + demand-driven + world-time-aware**，不通过固定 Tick 扫描整个世界。
48. Scheduler 只负责在 World Time 到达时重新产生 Runtime Work，不理解领域行为语义。
49. 没有有意义工作时，非实时 World 可以 fast-forward 到下一个有意义时间点。
50. World 持续存在不等于 Runtime 永久占用进程；Runtime execution 必须可暂停、持久化和恢复。
51. Scheduler、Reaction、External Input、Application、Process Continuation、Agent Deferred Work 等统一进入 Runtime Work Queue。
52. Work Item 只是待处理工作，不等于 Stimulus、Intent 或 Event；Work 可以最终被忽略而不产生历史变化。
53. Reaction 不递归直接修改世界，而应产生新的 Work，并受 depth / work / compute budget 约束。
54. Timeline Commit 是唯一线性化点；Resolution 可并行，但 Commit 必须依据最新 State 保持一致性。

## 7. Fast Path and cognition

55. Runtime 严格区分 **Fast Path** 与 **Cognitive Path**。
56. 机械性、确定性、流程化工作默认走 Fast Path，不需要 Agent 或 LLM。
57. LLM 是需要时才调用的昂贵认知执行器，类似高级思考能力；它不是 Agent 本身，也不是 Runtime 本身。
58. **Agent persists; compute is on demand.**
59. Agent 默认可以 dormant；Stimulus 不意味着模型调用。
60. Runtime 应先使用 deterministic routing、relevance filtering、routine、policy、heuristic、lightweight model、batching，再考虑昂贵 Cognition。
61. Agent 可 Wake 后仍选择 `NO_ACTION / WAIT / DEFER`；认知发生不代表必须产生世界行为。
62. Underlying model knowledge must never automatically become Agent knowledge or skill.

## 8. Agent-local view and context

63. Agent cognition 默认不能访问 omniscient World State。
64. Core 必须提供 Agent-local representation / perception boundary，使 Agent 可以拥有不完整、过时甚至错误的世界表示。
65. **Context is budgeted attention.**
66. Context 是 Runtime 临时构造的有限世界切片，不是 World State 副本和永久维护的大对象。
67. Actual World Context、Agent Context、Cognitive Context 是不同过滤阶段。
68. Visibility / access eligibility 必须先于 relevance；秘密再相关，只要 Agent 不可知就不能进入其 Cognitive Context。
69. Context 可以是多 Facet、重叠并随 Stimulus 动态变化。
70. Context Construction 必须受到 Entity、Relationship、retrieval、compute 和 token budget 约束。
71. Core 只保证 Agent 可以拥有跨 Wake 持续存在、Timeline-local、私有并可检索进入 Context 的内部状态；完整人类 Memory 模型不是 Kernel 强制语义。
72. Goal、Need、Plan、Personality、Emotion、Habit、Role Duty 等可以作为 Capability 提供的 Decision Driver / Bias，而不是 Agent Kernel 固定字段。
73. Core 定义 Agent 怎样在有限局部认知下形成 Decision/Intent；Capability 定义它为什么行动以及如何解释世界。

## 9. Affordance and access

74. Action Definition 描述一种可尝试行为；Affordance 根据当前 World/Timeline/Actor 状态动态计算。
75. **Can I?** 与 **Will I?** 分离；可行性不等于选择。
76. Actual Affordance 与 Perceived Affordance 分离；Agent 可以基于错误认知尝试失败，也可能因为不知道而错过真实机会。
77. Direct Affordance 与 Mediated Affordance 分离；“我做不了，但我知道谁或哪个渠道可能推进”是有效行动能力。
78. Social path 的每一跳都必须经过对应 Agent 自己的 Decision；中间人不是透明图节点。
79. Referral、Forward/Escalation、Delegation 是不同机制。
80. Planner 可以 Progressive Planning：只规划当前可达的一步，通过新信息和 Context 再展开下一步。
81. Relationship creates possibility, not guaranteed outcome.

## 10. Rule and validation

82. Loom 区分 **impossibility, prohibition, authority/permission and enforcement**。
83. Hard Runtime Invariant 应尽可能少，只保护 identity consistency、Timeline isolation、event sequencing、state/schema integrity、atomicity、referential integrity 等内核一致性。
84. Law / Policy / Norm violation 通常不等于 Commit failure；违法或违规行为仍然可以成为真实 Event。
85. Rule existence ≠ compliance ≠ detection ≠ judgment ≠ enforcement ≠ equal consequence.
86. Feasibility、Access、Authority、Permission、Legal/Policy Status、Social Norm Status、Enforcement Risk 是不同评价维度，不应压成一个 `allowed=true/false`。
87. Actual Rule 与 Agent Belief About Rule 分离。
88. Rule / Reaction Handler 不能直接修改世界，只能返回 Evaluation、Proposal 或新的 Work，由 Runtime 继续处理。
89. 确定性 Reaction 优先进入 Fast Path；需要主体自主判断时才形成 Stimulus 进入 Cognitive Path。

## 11. Capability boundary

90. Capability Module 定义领域语义，但不拥有 World Runtime、Timeline State、Event Ledger 或 Commit Authority。
91. Capability 可以贡献 State Facet、Relationship、Action、Resolver、Evaluator/Rule、Runtime Handler、Projection、Migration 等定义。
92. Capability Handler 是受 Core 调用的能力，不是独立后台 World Service。
93. Capability 不得直接访问并依赖 Core 内部数据库结构来修改世界事实。
94. Capability 之间不应互相调用内部实现形成耦合网；确有稳定协作需要时，通过 Core-owned contract / Event / Action / Relationship / Work 等协议完成。
95. Foundational Capability 与 Domain Capability 架构地位相同，只是复用范围不同。
96. Information、Institution、Goal、Planning、Human Memory、Emotion 等高级机制可以成为官方基础 Capability；重要性本身不是进入 Kernel 的理由。

## 12. World evolution vs software change

97. **Worlds evolve; software upgrades. Never confuse the two.**
98. World 内的新规则、新制度、新技术、新能力通过 Event / Rule / State 在自己的历史中出现并从相应 effective time 影响未来，而不是执行一个笼统的 `Upgrade World`。
99. 新规则不会修改其生效前已经发生的历史；旧规则仍然是过去当时适用的真实规则。
100. Core / Capability package version 属于软件实现、兼容性和可复现元数据，不是 World 内的时代版本。
101. Technical schema/storage migration 默认必须在世界语义上不可见，不产生虚假的 World Event。
102. 如果软件修复改变了未来的解析语义，已提交历史仍保持不变；若要查看“如果过去当时使用新语义会怎样”，使用 Fork / Replay 创建另一条 Timeline。
103. World Template 是出生配方；Template 后续变化只影响未来新建 World，不自动同步已创建 World。
104. Capability implementation 已安装、World 支持该语义、某 Timeline/Entity 此刻拥有实际 Affordance 是三个不同层次，不能压成单一 `enabled`。

## 13. Stable laws

105. **Identity belongs to World; mutable State belongs to Timeline.**
106. **Timeline is the history of the world; Trajectory is the history of an identity within that world.**
107. **No mutation without a committed Event.**
108. **Context is budgeted attention.**
109. **Agent persists; compute is on demand.**
110. **Worlds evolve; software upgrades.**
111. **Core owns existence, identity, time, history, state transition, cognition boundaries and orchestration. Capability owns semantics. Application owns purpose and experience.**

如果未来某个新设计与这些原则冲突，应先形成显式架构决策并说明替代关系，而不是在实现中静默改变基线。