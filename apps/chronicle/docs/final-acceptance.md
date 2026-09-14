# C1-T17 验收记录入口（已退役）

C1-T17 的交付和历史验收保留在[任务记录](../../../docs/tasks/chronicle/C1-T17-final-acceptance-gate.md)
以及对应 corpus 证据中。交付 PR #535、历史对账 PR #542 的结论不因本次清理改变。

原 C1 操作流程依赖分块 extraction/presentation 模型开关、旧 worker CLI
故障注入和 World/Timeline 页面。这些已不代表当前产品，本文不再提供旧的
生产运行指令；临时 T17 live-model Actions 工作流也已经退役。

当前正式生产使用 [worker.md](worker.md) 与
[staged-chapter-production.md](staged-chapter-production.md) 定义的整章分阶段流程。
仍被 CI 使用的冻结第一轮回归见 [chapter-acceptance.md](chapter-acceptance.md)。
[C3-T01](../../../docs/tasks/chronicle/product-convergence/T01.md) 负责把有效场景
迁入统一的当前验收入口，再删除旧 gate 与专属 helper。

程序校验通过不代表历史内容正确。当前任务仍须按自己的验收要求检查完整原文、
译文、来源归属、人物阶段和真实页面；不为普通开发自动重跑已完成的 C1 历史验收。
交付遵循仓库[完成流程](../../../docs/development/task-completion.md)，不额外要求
默认分支 Task Ledger PR/merge 对账。
