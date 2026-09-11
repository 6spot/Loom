---
task: C2-R2E-D02
issue: 660
kind: leaf
parent: C2-R2E
depends_on: [C2-R2E-D01]
---

# [C2-R2E-D02] 定义事实核对与叙事位置契约，落实 R3 交接

## 目标与前置

父任务：[#658](https://github.com/6spot/Loom/issues/658)（C2-R2E）；定稿前置：[#659](https://github.com/6spot/Loom/issues/659)（真实核对案例）。

把已确认产品方向落到同一套 Chronicle 应用合同，随父任务直接实现内容链路。原 R3 绑定来源 ReadingUnit；本任务明确新叙事如何复用人物阶段能力，避免后续两边各写一套事实或定位逻辑。

本任务保留合同与 R3 交接职责，后端、审核与正式页面由父任务同批实现；不再要求先增建实现子任务。实现、验证与测试机部署分别记录，不能把建议结构写成已经上线。

## 必读与输入

- 根 AGENTS.md、docs/development/README.md、docs/architecture/README.md 和相关 accepted Amendment 0006/0007。
- apps/chronicle/docs/ 下 chapter-production、data-contract、resolution、review-publication、reader-presentation、continuous-reading、reading-experience、person-state-reading。
- 当前历史叙事讨论记录及 D01 案例；已确认规则在父 Issue 中完整列出。
- 现有代码：resolve_publish、publication_v0、review_subjects、chapter/reading 发布与读取、useReadingPosition 和 EntityPage。
- [#550](https://github.com/6spot/Loom/issues/550) 及 [#617](https://github.com/6spot/Loom/issues/617)–[#633](https://github.com/6spot/Loom/issues/633) 的具体输入/输出与文件所有权。

## 拟交付文件与所有权

- apps/chronicle/docs/source-corroboration.md（新）：来源主张、比较问题、结论、依据关系与审核评估的 canonical 应用合同。
- apps/chronicle/docs/historical-narrative-design.md：将已确认方向中的叙事/位置/下游关联细化，明确合同所有者，不重复事实核对规则。
- 相关旧应用合同：只修改被替代的具体条款与指向，保留来源阅读含义和现有权威边界。
- docs/tasks/chronicle/reading-enhancement/ 与 third-round/ 中受影响的规划说明及对应 GitHub Issues。

D01 的 cases/source 文件只读。shared schema、provider、数据库、router、App 和 dist 随父任务按依赖顺序接线，避免重复实现。

## 需要明确的合同

1. 来源原话/Claim、比较问题、候选结论和审核决定分别保存什么；人物同一、事件同次、事实互证不得互相替代。
2. 何时可比较相同主体/事实维度/阶段；支持、部分支持、补充、反驳、背景和暂不可比较如何表达及校验。当前日期不一致的候选筛选不能让真正需要核对的材料永远消失，也不能因此自动归并事件。
3. 作者/注文/书信/转引及来源传承如何保留；独立性未知时怎样表达；不按数量或模型自报 confidence 判真伪。
4. 模型一次完整章联合抽取提供哪些来源候选，跨来源核对又消费哪些上下文、产生哪些建议。结论明确性由审核和阶段适用性决定；不新增读取时生成或补写路径。
5. 围绕具体问题的审核载荷、完整上下文、批量/例外范围、未知/分歧决定、重试/恢复、并发修改和长页连续操作。展示分组不能获得新的身份权威。
6. 综合叙事生成、结论证据绑定与发布：原文、结论、正文、导航版本固定；新增资料如何定位受影响结果并重新核对；沿用唯一生产/事务机制，明确在哪个阶段接入。
7. 正序正文如何分批生产并连续读取，事件/时期入口如何只定位；新叙事片段到事实阶段、人物/地点/事件与来源位置怎样对应。不可把旧来源 unit 的编号或含义直接改作综合段落。
8. 主历史正文和人物生平共用哪些事实与版本，各自的叙事表达怎样关联；人物页三栏职责已确认，精确入口/缺失阶段/返回行为需写清。
9. R3 的官职/爵号/效力等专门状态算法，与地点行政归属/实际控制如何各有界限；此处定义共用扩展点，专门算法和完整人物页由修订后的 R3 交付。
10. 首版不引入任意因果推理。来源明确解释、当事人说法与编者推断分别表达，不能把新语义暗塞进旧 Reader block contract。

## 实现与下游交接

| 内容 | 当前合同／实现交接 |
| --- | --- |
| 事实与叙事 JSON | `narrative_contract.py`、`narrative-types.ts`；引用、主体、阶段、完整覆盖与精选入口校验 |
| 显式生产与纠错 | `narrative_stage.py`；完整章输入、两次审核、同一冻结输入失败稿续用 |
| 持久化和发布 | `narrative_store.py`、迁移 0008；原锁、租约、版本固定和不可变记录 |
| 审核 | `NarrativeReviewPanel`；结论逐条核对、完整原文定位、草稿、页底保存／下一项 |
| 正文读取 | `read_api/history.py`、`history-api.ts`；固定版本的段落、阶段、结论与来源 |
| 正式页面 | `HistoryPage`、`HomePage`；少量入口、正序阅读、紧凑当时状态、按需资料与原位返回 |
| R3 扩展 | 来源阶段推理、专门任期算法和人物详情；共享已审核结论，不再建立另一套真伪判断 |

R3 的机器接口须消费综合 `{version, paragraph_id, phase_id}`；来源 `{stream_id, unit_id}` 只表示原书译文。D02 使用正式组件检验交互；T01/T09/T10/T11/T13 及迁移编号按本次交接修订。独立模块按具体接口具备情况开展，共享路由、控制器和构建串行接线，不要求多个分支。

GitHub/task 记录需求、标准与具体依赖，不恢复默认分支 Task Ledger PR/merge 对账。

## 验收与验证

- [ ] D01 的每个真实/合成案例都有合同覆盖及明确禁止结果，尚未解决的语义不能隐藏成实现者自由选择。
- [ ] 准确列出旧合同被替代的条款，来源阅读、身份确认、事实评估和派生正文只有各自单一语义所有者。
- [ ] 审核/发布/读取的版本、错误、恢复与大小边界可实现且可测试；正文不能依靠现场模型调用。
- [ ] 新旧阅读位置映射与 R3 数据交接具体，提供示例载荷/场景；尚未实现字段不写成当前代码能力。
- [ ] 父任务直接实现所需模块，R3 受影响任务同步修订；不再要求新建实现叶任务或 Task Ledger 对账。
- [ ] 本地文档链接/格式与任务依赖无环检查通过，准确区分单测、合成交互、真实模型内容核对和测试机验证。

如发现需要改变 Loom 注册存储或 canonical 身份权威，先按架构流程解决；应用字段本身不自动要求新 Amendment。采用新开发测试数据，不引入旧数据迁移或双生产链。
