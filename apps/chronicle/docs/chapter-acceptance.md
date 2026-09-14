# C2 第一轮验收操作指南（篇章生产离线门 + 真实模型验收）

> 本文的 fixture gate 仍用于现行 CI 回归，使用冻结的早期章节合同。
> 它不等于当前 staged 0.4 的生产验收。旧 live 预检查将在
> [C3-T01](../../../docs/tasks/chronicle/product-convergence/T01.md) 中替换；
> 当前生产配置与步骤验证见 [worker.md](worker.md) 和
> [staged-chapter-production.md](staged-chapter-production.md)。

本指南是第一轮唯一的验收操作入口，由 C2-R1-T18 拥有。C1 历史结论见
[final-acceptance.md](final-acceptance.md)，本文不改写 C1 记录。

契约权威：[chapter-production.md](chapter-production.md) §9、
[review-workflow.md](review-workflow.md) §5。任务台账：
`docs/tasks/chronicle/first-round/T18-offline-end-to-end-gate.md`（离线门）、
`T19-live-content-acceptance.md`（真实内容验收）。

## 1. 离线门（fixture mode，CI 运行）

统一编排入口 `apps/chronicle/acceptance/first_round_gate.py`。fixture
模式完全离线、确定性：用真实 `plan_chapters` 规划冻结 T02 语料包
（`apps/chronicle/corpus/first-round/` 两部著作输入），经生产章切片
hash 绑定生成确定性 fixture 候选，用 T01 规范校验器验收、T07 装配、
T08 同 revision 跨章 pair 与冻结审核计划指纹，再执行故障注入。
脚本只编排产品 API 与 Compose，不直写产品 DB（无 DB 驱动导入、无 SQL）。

fixture 结果明确标注非 live，**不能作为真实内容正确证明**。

准备 env 文件（按本指南准备，不提交秘密）：

```bash
cat > /tmp/chronicle-first-round-test.env <<'EOF'
CHRONICLE_POSTGRES_PASSWORD=test-only-local
CHRONICLE_ADMIN_USER=admin
CHRONICLE_ADMIN_PASSWORD=test-only-local
EOF
```

运行离线门与 scoped 测试：

```bash
python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_first_round_gate.py' -v
python3 apps/chronicle/acceptance/first_round_gate.py --mode fixture --env-file /tmp/chronicle-first-round-test.env --source-pack apps/chronicle/corpus/first-round/source-pack.json --evidence-dir /tmp/chronicle-first-round-offline
```

成功后 `/tmp/chronicle-first-round-offline/manifest.json`（schema
`chronicle.first-round-gate-evidence/0.1`）记录：候选 commit 与
`git_clean`、实际命令、来源/产物 hash、模式、job/review/publication
占位、浏览器脚本与日志定位。失败时保留
`manifest.partial.json`（已完成阶段 + 失败原因），原成功结果不被覆盖。

离线覆盖（详见 T18 台账与 manifest `works`/`faults` 段）：

- 章内 ref 共享（local temp ID 同章共用）、同 revision 跨章 pair
  （`chapter_pair`，初始 `uncertain`，阻塞，不自动合并）、跨书
  batch/default/override DTO（默认 `uncertain`，逐组例外保留）、
  `uncertain` 不合并、无 Claim 记录的原文 provenance（record_source）、
  首尾译文覆盖、多对多引用（多译文块 × 多实体/事件）。
- 故障注入：run 接受间中断后幂等重验收养、worker 接管/取消（空作业
  不装配）、缺一章、超限/length、source hash 错误、公开事务回滚
  （坏 resolution 不验证 → 无部分发布）、同 revision 内容变更拒绝、
  两 revision 阅读隔离（装配拒绝混 revision，章身份不跨 revision 碰撞）。
- 浏览器复用：`review-flow-smoke.mjs`（450+ 审核队列与连审）与
  `chapter-reader-smoke.mjs`（Reader 路线）静态复用检查；fixture
  不启动浏览器、不复制第二套客户端逻辑。live 才真实执行。
  `review-flow-smoke.mjs` 另有 `--mode real-backend`：不 mock Studio
  HTTP，用环境变量 `CHRONICLE_SMOKE_USERNAME` / `CHRONICLE_SMOKE_PASSWORD`
  （或 `--username` / `--password`）登录真实实例，打开准备好的
  `--review-id`，提交裁决并读回 `status=resolved`；账号密码不落仓库与日志。

## 2. 历史 live 预检查

T18 的旧 live 模式只做早期配置预检查，不执行模型。它要求的 C1
extraction/presentation 开关已经从正式生产入口删除，因此 `READY` 不能
证明当前流程可运行，不再作为新任务的生产操作指令。

早期 T19 的执行与内容结论保留在第一轮任务和 corpus 验收记录中。
新任务通过当前整章流程完成上传、逐步处理、异常审核、发布和真实阅读核对，
并分别记录程序结果与内容质量。C3-T01 负责将这些场景接到统一的当前验收入口。
