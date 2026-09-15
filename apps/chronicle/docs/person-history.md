# 人物生平生产与审核

人物生平是独立于主历史正文的两个产品：一个“概况”摘要和一份按阶段展开的
“经历正文”。两者都针对一个已发布的 canonical person 和 Studio 明确选定的
完整来源生成；它们不能通过筛选主历史段落或扩宽 `historical_narratives` 得到。
本合同覆盖 C3-T12 的生产、持久化和审核接线；公开人物页由后续读取任务负责。

## 冻结输入

Studio 创建任务时必须提交 `person_id`、`catalog_sha` 和一个或多个
`publication_ids`。`person_id` 必须是该冻结 catalog 中已经发布、并且出现在所选
完整章节 canonical 引用中的 person。程序按已发布章节读取完整原文、译文、证据锚点、
已审核人物状态和来源 Claim；未发布候选、同名但未确认的人物以及按姓名或年份猜出的
匹配都不会进入 context。

任务把以下关系写入 `ingestion_jobs.checkpoint.person_history_scope`，并把模型选择
作为不可变的 `studio-production-request` 输出保存：

```json
{
  "person_id": "<canonical person UUID>",
  "catalog_sha": "<published catalog SHA-256>",
  "publication_ids": ["<complete publication UUID>"]
}
```

模型提示使用程序生成的临时句柄，候选返回后再恢复并校验 canonical ID、证据、已批准
结论、事件、关联人物／地点和主历史位置。完整输入超过预算时任务失败或进入例外审核，
绝不截断来源。新 catalog、来源集合或模型／提示配置必须创建新任务；旧候选和已发布版本
保持不变。

## 四个模型步骤（T04–T06 adapter）

人物生平复用共享 `StepRunner` 的租约、并发、重试和 `ingestion_outputs` 记录，不建立
第二个 worker 调度器。逻辑步骤为：

1. `summary_generate`：从完整冻结资料产生结构化概况候选；
2. `summary_compare`：多模型时只比较固定候选集，无法解释分歧就进入人工例外；
3. `prose_generate`：只消费已接受的概况，产生覆盖全部 life phase 的独立正文候选；
4. `prose_compare`：同样比较固定正文候选。

每个 attempt 先保存完整 prompt、输入指纹、模型配置和尝试编号，再保存原始响应、解析
结果、验证错误、状态和用量。成功结果只在相同 pipeline、step、round、slot、输入、
prompt 和模型配置下复用；失败、无效或部分模型结果不会被当成“无异议”。

## 候选 schema 与内容边界

`persistence/person_history_contract.py` 拥有
`chronicle.person-history-summary`、`chronicle.person-history-prose` 和比较报告的
JSON Schema 与语义校验。摘要至少保存 overview、birth/death（无明确证据时必须为
`null`）、按时间顺序的 phase 和结论。每个 phase 记录依据、相对先后、主历史对应状态
和理由；对应可以是：

- `mapped`：有一个可靠的主历史 paragraph；
- `ambiguous`：有多个给定候选，全部保留；
- `unmapped`：没有可靠对应，位置字段为空并写明原因。

结论的状态维度仅为 `office`、`title`、`allegiance`；行动使用 `action`，不把参战、
出使或到访改写成官职、效力或地点控制。`related_person` 和 `related_place` 必须
链接已有 canonical entity。每项结论和正文 segment 都必须引用冻结 evidence 与
approved conclusion；原文没有明确生卒时不从首次／末次出现推断日期。

概况与正文都逐字使用覆盖声明“根据当前收录资料整理的经历”，并保存
`exhaustive: false`。这表示有限来源范围，不声称穷尽人物一生，也不补造阶段之间的
过渡。

## 接受、修订和发布

`person_history_candidates` 是按 job/kind 的追加式 frontier；`person_history_acceptances`
保存独立的摘要／正文接受 receipt，`person_histories` 保存同时拥有两个已接受产品的
不可变发布版本，`person_history_mappings` 保存每个 phase 到主历史 paragraph 的显式
映射。数据库触发器校验候选父版本、冻结 context、receipt hash，以及发布时两种 kind、
job、context 和 acceptance 的绑定关系。

候选没有完整模型链、比较报告有未决争议、来源／身份／阶段校验失败或人工修订后，都会
进入 `scope=person_history` 的 `stage_gate` review。接受必须原样批准通过校验的候选，
并提交 `reviewed_conclusion_ids`：摘要覆盖全部结论，正文覆盖其引用的全部结论。人工
修改不能和批准放在同一决定中；`revise` 会追加新候选、使旧审核失效并重新审核；
`reject` 取消任务。自动 policy receipt 也必须绑定完整模型输出、比较意见、pipeline
fingerprint 和结论覆盖，不能仅凭一个“通过”字段发布。

发布发生在共享 publish lock 和 job lease 下。只有摘要、正文都已接受且 catalog 仍是
冻结版本时，才一次性写入 person-history publication 与 mapping rows；失败不会写半份
公开结果。普通读取请求不生成内容。失败／取消任务可通过 Studio 的 `new-run` 沿用同一
人物和来源选择，但新运行仍重新验证 catalog、完整章节和父任务 revision。

## 公开读取

人物页通过以下匿名 GET 路由读取已经发布的独立版本；读取只访问
T12 的 `person_histories` 和 `person_history_mappings` 作为生平正文与映射权威；只为
精确身份、关联对象名称和按需原文锚点读取既有公共索引，不会读取候选／审核 frontier，
也不会在请求中生成或写入内容：

- `GET /api/v1/public/entities/{person_id}/history`：人物姓名、已审核概况、时间精度、
  资料覆盖、阶段映射和首段。没有发布版本时仍返回 `status: "empty"` 的真实空态。
- `GET /api/v1/public/entities/{person_id}/history/paragraphs?version&at|start&limit`：
  `version` 固定人物生平发布版本，`limit` 为 `1..50`；响应带 `start`、`total`、
  `previous_start` 和 `next_start`，段落只返回证据 ID，不展开全部依据。
- `GET /api/v1/public/entities/{person_id}/history/conclusions/{id}?version`：固定人物
  生平版本读取一个结论，并按需返回其真实 `source publication/anchor` 引用。

元数据路由可附带 `version={main_history_version}&paragraph_id={main_history_paragraph_id}`
从主历史入口定位人物阶段；若要同时固定人物版本，使用 `person_version`。主历史版本和
段落只通过已发布 mapping/index 精确匹配，`mapped`、`unmapped`、`ambiguous` 以及全部
候选目标均明确返回，绝不按姓名、年份或阶段 ID 猜测。

T13 的 PostgreSQL fixture 读取还保留了四个阶段的脱敏结构响应，供后续人物页接线使用：
`read_api/fixtures/t13-redacted-person-history-phases.json`。其中只保留响应 schema、阶段
数量、映射状态、分页边界和状态／行动计数，不把 fixture 当作真实史料验收。

## Studio 接口

人物选择与生产入口位于现有 Studio jobs router：

- `GET /api/v1/studio/jobs/person-history/people`：可带 `catalog_sha`、重复的
  `publication_ids`、`limit`、`offset`，返回选定完整来源中已确认的 canonical people；
- `GET /api/v1/studio/jobs/person-history/model-options`：返回现有 narrative model
  catalog；
- `POST /api/v1/studio/jobs/person-history`：提交上述三项固定选择，可选
  `model_selection`，返回共享 `IngestionJob`；
- `GET /api/v1/studio/reviews/{review_id}`、`/contexts` 和 `/decision`：复用统一审核
  生命周期，人物生平的来源／证据通过 contexts 返回，决定体支持 approve、reject、
  revise 和 `reviewed_conclusion_ids`。

任务列表、详情、动作状态、结果分页和 acceptance projection 使用现有 Studio 投影，
只额外标记 `job_kind=person_history`、人物生平标签和 person-history result types；模型
prompt、原始响应、请求配置和服务器路径仍不直接暴露给浏览器。
