---
task: C2-R2-D01
issue: 588
kind: leaf
parent: C2-R2
status: completed
depends_on: []
created_at: 2026-09-08
started_at: 2026-09-08
completed_at: 2026-09-09
completion_pr: 592
merge_sha: 65b8f4858e1df56c441f6c6969d265a139f01752
---

# 可复用历史背景图技能与人工素材工作流

## Scope

[Issue #588](https://github.com/6spot/Loom/issues/588) owns the implementation steps. 独立的设计准备：仓库技能、离线候选素材归档/检索、按时代调整的画风与人工背景工作流。产品上传、人工保存/关联、公开读取与页面背景渲染属于后续待拆分工作，不在本叶交付中。

Canonical design: [background art](../../../../apps/chronicle/docs/background-art.md). Reusable skill: [historical-background-art](../../../../.agents/skills/historical-background-art/SKILL.md). Coordination: [initiative index](README.md).

## Acceptance

- [x] 技能可发现、无未完成模板，支持不同题材/时代及库路径。
- [x] 仅明确的图片生成请求触发生成；仅对具体版本和位置的人工保存允许产品启用。
- [x] 离线候选归档与检索保留原图、提示词、元数据和完整性信息；重复导入不覆写，破损能报告。
- [x] 背景工作流和时代画风进入 canonical 设计；无正文插图或自动生成的默认路径。
- [x] 实际验证证据、交付 PR/merge 和默认分支对账完整；未来 Studio/页面能力没有被标成完成。

## Verification

2026-09-09 本地验证：

- `python3 -m unittest discover -s .agents/skills/historical-background-art/scripts -p 'test_*.py' -v`：10/10 通过，覆盖实际 CLI 归档/检索/读取、并发幂等、原图保留、衍生版本、未知提示词、候选状态和损坏/路径检测。测试像素仅在临时目录，不是生成图验收。
- `skill-creator/scripts/quick_validate.py .agents/skills/historical-background-art`：通过；本机系统 Python 缺少 PyYAML，使用仓库外临时 venv 安装 PyYAML 6.0.3 后运行，没有新增项目依赖。
- first-round/second-round 组合 Task Ledger：39 条记录，无缺失依赖或完成规则违规；原17个阅读产品叶没有 READY 项。
- `library.py --library apps/chronicle/assets/backgrounds verify`：通过，0 张实际候选；`check_storage_sql_ownership.py` 通过。
- [PR #592](https://github.com/6spot/Loom/pull/592) 实际 head `d2b29c97d39c0e1021e7c7792564b3c08063babb`：更新后的 [CI](https://github.com/6spot/Loom/actions/runs/34250793295) 与 [Validator](https://github.com/6spot/Loom/actions/runs/34250793163) 运行，Repository Gate / Validator Gate 均通过；12项检查 success、2项通知 skipped。本次未修改产品 source/dist、SQL、公开 API 或 workflow。
- 技能 UI metadata 检查通过，67个本地文档链接有效，提交 whitespace 通过；依赖图无环，T17覆盖新增D01在内的18个叶。

没有运行图像生成、图片上传端点、生产页面或模型行为测试。人工触发/保存规则通过技能与设计文本核对；它们不等于尚未开发的产品权限门已通过运行验收。交付 PR #592 已于 2026-09-08 16:36:19 UTC squash 合并；本记录以实际 merge SHA 对账，需到达默认分支并回读后才关闭 #588。

## Progress Log

- 2026-09-08 — 用户明确要求可复用背景图技能，并纠正为仅页面背景、AI 只建议、人工触发生成/上传、人工校验后保存才展示。本叶先行交付设计准备，原 17 项产品任务的前置继续有效。
- 2026-09-09 — 技能、离线候选工具及 canonical 背景设计已编写；本地10项验证和技能格式检查通过。初测中民国样例遗留赤壁位置建议，修正测试样例的题材信息后检索检查通过，未缩小真实搜索范围。等待交付 PR 和合并后对账。
- 2026-09-09 — PR #592 通过实际 CI 后合并为 `65b8f4858e1df56c441f6c6969d265a139f01752`，补齐完成日期、验收和父索引。仅D01设计准备完成；背景产品上传/保存/读取/展示仍待拆分与实现。
