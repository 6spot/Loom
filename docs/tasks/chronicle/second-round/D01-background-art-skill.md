---
task: C2-R2-D01
issue: 588
kind: leaf
parent: C2-R2
status: in_progress
depends_on: []
created_at: 2026-09-08
started_at: 2026-09-08
completed_at:
completion_pr:
merge_sha:
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
- [ ] 实际验证证据、交付 PR/merge 和默认分支对账完整；未来 Studio/页面能力没有被标成完成。

## Verification

2026-09-09 本地验证：

- `python3 -m unittest discover -s .agents/skills/historical-background-art/scripts -p 'test_*.py' -v`：10/10 通过，覆盖实际 CLI 归档/检索/读取、并发幂等、原图保留、衍生版本、未知提示词、候选状态和损坏/路径检测。测试像素仅在临时目录，不是生成图验收。
- `skill-creator/scripts/quick_validate.py .agents/skills/historical-background-art`：通过；本机系统 Python 缺少 PyYAML，使用仓库外临时 venv 安装 PyYAML 6.0.3 后运行，没有新增项目依赖。
- first-round/second-round 组合 Task Ledger：39 条记录，无缺失依赖或完成规则违规；原17个阅读产品叶没有 READY 项。
- `library.py --library apps/chronicle/assets/backgrounds verify`：通过，0 张实际候选；`check_storage_sql_ownership.py` 通过。
- GitHub CI 的现有 path filters 不覆盖本次技能/设计路径；交付时回读 PR 的实际检查状态。未修改产品 source/dist、SQL、公开 API 或 workflow。

没有运行图像生成、图片上传端点、生产页面或模型行为测试。人工触发/保存规则通过技能与设计文本核对；它们不等于尚未开发的产品权限门已通过运行验收。交付合并及默认分支对账尚待完成。

## Progress Log

- 2026-09-08 — 用户明确要求可复用背景图技能，并纠正为仅页面背景、AI 只建议、人工触发生成/上传、人工校验后保存才展示。本叶先行交付设计准备，原 17 项产品任务的前置继续有效。
- 2026-09-09 — 技能、离线候选工具及 canonical 背景设计已编写；本地10项验证和技能格式检查通过。初测中民国样例遗留赤壁位置建议，修正测试样例的题材信息后检索检查通过，未缩小真实搜索范围。等待交付 PR 和合并后对账。
