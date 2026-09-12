# Chronicle 第一轮：章节内容生产与完整译文契约

新任务的整章纯译文、独立提取、阶段保存及内容审核由
[分阶段章节生产（0.4）](staged-chapter-production.md) 接续。下文 0.1–0.3
联合生成与原注翻译规则用于解释这些冻结版本；0.4 不再使用一次联合输出。

状态：**本轮实现契约，尚未实现**。协调 Issue [#548](https://github.com/6spot/Loom/issues/548)，执行图见 [第一轮 Task Ledger](../../../docs/tasks/chronicle/first-round/README.md)。本文固定实施选择，不把当前 C1 代码描述为已经具备这些能力。

第二轮的 0.2 阅读注解、连续 stream 和事件位置扩展见 [continuous-reading.md](continuous-reading.md)，由 #549 的独立任务交付；本文的第一轮 0.1 验收不以第二轮实现为前提。

第三轮的 0.3 人物阶段资料扩展见 [person-state-reading.md](person-state-reading.md)，由 #550 的独立任务交付；完整章联合生成、原文锚点和不可变发布仍沿用本文基础合同。

已发布完整章可作为 [多史料综合叙事](source-corroboration.md) 的输入。该任务由
Studio 显式选择来源后创建，章节导入本身不自动重写公开历史正文。抽取事件
也不自动成为前台锚点；完整战事、评价、小事实及状态按其语义保存，导航由
综合正文的第二次审核选择少量重要时期与事件。

## 1. 结果与边界

以自然章节为完整语义单元，在同一上下文中生成完整白话译文、人物／地点／政权／事件和原文依据；经过校验、关联审核和发布后，读者可以阅读全文，按需查看对应古文。展示分段不是独立翻译调用。

复用 Document / Revision、PostgreSQL 任务和租约、C0 staged Entity/Event/Claim、Resolution、人审和 canonical publication。新增数据仍受 [Amendment 0006](../../../docs/architecture/amendments/0006-application-owned-product-persistence.md) 约束；[Amendment 0007](../../../docs/architecture/amendments/0007-chronicle-resolution-review-subjects.md) 的批次不是身份等价、逐组例外和 candidate-level fan-out 保持不变。

本轮保留 **一份上传 revision → 一个 source-owned staged bundle**。章只是该来源的处理与引用单位，不增加“独立史料数”。同章确认的称谓共用 local temp ID；跨章表示通过同一个映射进入 revision namespace，再单独审核身份。原 publisher 已能消费同 bundle 不同 ref 的 same-link；需要扩展的是候选生成、Resolution 应用约束和未发布两端的审核组织，不改变 canonical union 规则。

这些选择属于既有 Chronicle 产品权限内的实现契约，无需仅为字段、表或来源内候选新增 Loom Amendment。不得将章分组、模型置信度或名称变成自动 canonical 合并依据；若实施要求改变该边界，按 Architecture Index 处理 Amendment。

使用全新开发测试数据库，不做旧产物、旧 UUID、旧 schema 数据迁移或双轨生产。已完成 C0/C1 的记录和局部回归保留。第二轮时间轴／事件悬停／当前片段联动、第三轮人物时态、Why、地图不进入本轮验收。

## 2. 输入、章节与定位

### 2.1 首轮支持格式

继续只接收受控 UTF-8 `.txt/.md`，上传大小沿用现有 10 MiB 限制。

- 单篇 `.txt` 是一个完整自然章；内部书信题目、引文或“第十三”等文字不触发重新切章。
- 多章材料使用 Markdown：可有一个 `# 著作标题`，每个 `## 自然章标题` 是一个章，`###` 及以下小标题属于所在章。章结束在下一个同级或更浅标题前。多个冲突的一级著作标题拒绝为 `chapter_structure_ambiguous`。
- 没有二级章标题的材料按一章处理。首个章前的非空实质内容形成“前言”章；书名行和空白可标为 heading/separator，但不得丢弃原文。
- 不把当前 `Section.source_end` 当章末尾：旧 section 到下一个任意标题为止。新章范围必须覆盖其后代小标题。
- 首轮不增加可视化章节编辑器、OCR 或自动判断任意书籍排版。语料准备任务把已核对的自然章明确包装成上述格式，并保留每章到原下载文件的对应关系。

`plan_chapters(text, revision_locator, filename)` 是纯函数；版本固定为 `c2r1-chapters-v1`。输出章顺序、标题、原文范围、block manifest 和 plan hash。不可跨章重叠，也不可遗漏除已登记 heading/separator 外的非空内容。

### 2.2 两种 hash 与坐标

原始文件 bytes 不修改，`source_sha256` 对它计算。复用 `documents.decode_source()` 去一个 BOM、CRLF/CR → LF，另算 `normalized_sha256`。

所有章、block、锚点使用 `offset_unit: chars-normalized-utf8`，即规范化文本的 Unicode code point 半开区间 `[start,end)`。不是原始字节，也不是浏览器 UTF-16 索引。读取时先核对原始 byte hash，再 decode；服务端返回切好的正文／高亮片段，浏览器不自行猜偏移。

`chapter_id = ch_ + sha256(canonical_json(revision_id, source_sha256, start, end, plan_version))[:24]`；block 和 anchor ID 同样按其完整绑定生成并检测冲突。ID 不是历史身份。原文 block 以段落／显式小标题为边界，保留分隔符范围；单个长段不因展示长度成为独立翻译调用。

`ChapterPlan`：

| 字段 | 约定 |
| --- | --- |
| version / plan_sha256 | 计划版本和整个有序计划的 hash |
| document_id / revision_id / source_sha256 / normalized_sha256 | 固定同一不可变 revision |
| chapter_id / chapter_index / title / start / end | 章身份、0 起始顺序、标题、绝对规范化字符范围 |
| blocks[] | block_id、kind(body/heading/separator)、start/end、content_sha256 |
| required_block_ids[] | 所有非空 body block，必须出现在译文的来源覆盖中 |

段内注释原样保留，首轮采用“正文及现存嵌注全部翻译”。译文保留“某书记载／裴松之按”等归属，不把注释中的转述或分歧改写为正文断言。不把书名引号自动判成独立注释层；更精细版本整理不在本轮。

## 3. 模型调用和容量

首版选择 **一次完整章联合生成 + 至多一次完整章重生成修正**。两次均包含同一完整章原文、所有 block、同一 schema 和来源元数据；修正附有有界错误清单。不同展示段落不分别调用模型。跨章不靠有限前后文续写身份。

默认容量是工程上限，不是模型能力／正确率保证：

| 配置 | 默认上限 |
| --- | ---: |
| normalized chapter chars | 32,768 |
| 最终渲染 prompt chars，含 schema／metadata／修正错误 | 262,144 |
| accepted/raw response chars | 524,288 |
| HTTP response bytes | 4 MiB |
| provider 请求 max_output_tokens | 65,536 |
| 每次章执行的语义生成轮数 | 2（初次 + 最多 1 次修正） |

参数由 `ChapterLimits` 固定进入 request fingerprint。环境变量依次为 `CHRONICLE_CHAPTER_MAX_SOURCE_CHARS`、`CHRONICLE_CHAPTER_MAX_PROMPT_CHARS`、`CHRONICLE_CHAPTER_MAX_RESPONSE_CHARS`、`CHRONICLE_CHAPTER_MAX_RESPONSE_BYTES`、`CHRONICLE_CHAPTER_MAX_OUTPUT_TOKENS`；修正轮数固定为 1。provider 必须支持所配置的 context/output 规模；真实预检记录请求、返回用量及终止状态，不能把字符上限当 token 上限。输入不适配、provider 拒绝窗口、incomplete/length、响应超限或第二次仍不合格均整体失败，留下原文和错误。禁止截断后当成功，禁止静默回退旧 chunk 生产。

HTTP 运输重试沿用现有最多 3 次，和上述内容修正分开计数；job/租约重试继续受既有有限状态机约束。请求 fingerprint 和 run 历史记录实际模型、prompt/schema/plan/limits 版本。修正不塞回无限大的旧响应：完整章 + schema + 有界错误要求重新生成完整产物。

0.2/0.3 联合产物的纠错按完整验证报告区分元数据修复与正文结构修复。仅修元数据时保留原有段落 ID、顺序及全文，结果仍是完整联合产物；缺段、正文超限等仍可完整修复。具体诊断预算、版本绑定和两稿重放程序见 [extraction.md 的纠错完整性说明](extraction.md#correction-integrity-for-02-and-03)。该限制防止纠错删文，不证明初稿翻译完整或正确。

## 4. 联合产物：机器契约的固定形状

模型仅生成 `chronicle.chapter-candidate / 0.1`。程序补齐 hash、offset、DB ID 和 canonical 映射，模型不能生成它们。

| candidate 字段 | 内容 |
| --- | --- |
| schema / version / chapter_id | 固定标识，chapter_id 必须原样匹配请求 |
| bundle | 既有 C0 staged bundle；Source/Entity/Event/Claim，全部 temp_id，无 canonical id |
| translation.language | 固定 zh-CN |
| translation.blocks[] | 唯一 block_id、有序 text、非空 source_block_ids[]、entity_refs[]、event_refs[] |
| mentions[] | 唯一 mention_id、surface、contextual、status、target_ref 或 null、candidate_refs[]、selection |
| record_sources[] | record_ref + 非空 selections[]；每个 Entity/Event/Claim 都能追到原文 |
| warnings[] | 原文不足、未解指代、时间／事件边界问题；不能靠 warning 绕过结构校验 |

引用类型是带 kind 的 `{kind: entity|event, ref: temp_id}`；Claim 另用 record_ref。数组顺序有意义，空集合返回 []。

`selection` 固定为 `{first_block_id,last_block_id,quote,occurrence}`：两个 block 在同一章且顺序合法；quote 在它们覆盖的连续原文中逐字匹配，occurrence 是从 1 起算的出现次数。常见单段引用两端相同。所有出现的位置由程序枚举核对；不能只 `find()` 取第一个。译文 block 的 source_block_ids 是多对多出处，不要求逐句对齐。

`mentions` 中 resolved → target_ref 非空且候选集为空；ambiguous → target_ref=null 且至少两个有效候选；unresolved → target_ref=null，可无候选。surface 必须等于该 selection.quote。相同语境下“曹操／操”可指向同一个 Entity；“公／王”保留为 contextual mention，不进入稳定 aliases。别名有原文支持才保留；未明确指代不强制配给最熟悉的人。

事件沿用原 time/participants/places 与 Claim 契约；不得把建安某月当成公历同月。Normalized 年份仅来自已验证的来源映射，month/day 无换算器时为 null。人物在事件中的 role 可以保存；跨时期身份状态仍属于第三轮。

`validate_chapter_candidate(request, candidate)` 生成完整报告；`accept_chapter_candidate(...)` 仅对通过者生成 `chronicle.chapter-artifact / 0.1`，其中包含 candidate、解析后的 anchors、请求 fingerprint 与 producing-run 绑定。每个 anchor 固定 revision/source hash/chapter/start/end/quote hash；译文来源 block 自动对应 block 范围 anchors。

必须检查：schema、ID/引用闭合、kind 匹配、无 canonical ID、所有 Entity/Event/Claim 的 record_sources、Claim.evidence.text 与首个 selection.quote 相等且 source_ref 正确、mention 一致性、完整 required_block_ids 覆盖、重复 quote 次数、范围/hash、章节和请求版本一致。覆盖检查只证明“没有完全未关联的原文段”，不证明译文完整或语义正确；最后仍需逐章内容核对。

合同 fixture 包含：有效完整章、缺末段、仅结构无译文、仅译文、悬空 ref、同名歧义、跨段 quote、重复 quote、BOM/CRLF/扩展汉字、无直接 Claim 的人物、非法月份与 source hash 不符。fixtures 是局部契约材料，不冒充真实模型验收。

## 5. 持久化与处理步骤

保留既有八阶段和 PostgreSQL 任务模型：

`prepare → structure → segment → extract → assemble → resolve → publish → present`

- `structure/segment` 使用新 ChapterPlan；复用 `ingestion_chunks` 作为工作单元，每章恰好一项。不另建第二套队列或 chapter-run authority。
- `extract` 调用完整章生成；复用 append-only `ingestion_chunk_runs`。accepted checkpoint 指向完整章 artifact，不可单独接受一份译文或一个 bundle。
- `assemble` 使用全部预期 accepted 章；按 `(chapter_index, local_ref)` 统一 remap 到 revision refs。译文 entity/event refs、mentions、record_sources 和 C0 字段都用同一映射。输出仍为 `assembled-source-bundle`，report 增加 chapter manifest、chapter_by_ref、artifact hashes、local-to-revision map。
- `resolve` 消费 §6 的统一 frozen plan。
- `publish` 消费全部人审决定并执行 §7 的原子发布。
- `present` 对章译文只核对已经发布的版本，不再次翻译。既有人物／事件简介可以继续作为独立可选派生能力；不是本轮章译文的依赖或替代品。

新增唯一迁移 `0006_chronicle_chapters.sql`，由章存储任务独占：

| 表 | 内容与约束 |
| --- | --- |
| chapter_artifacts | artifact_sha256 PK，job/revision/chapter/chunk/producing-run、request_fingerprint、payload；不可变，完整联合产物只通过 accepted 写入口形成 |
| chapter_publications | publication_id(UUIDv7)、artifact_sha256、catalog_sha256、assembled_bundle_sha256、document/revision/chapter、publication payload 和 published_at；同 artifact+catalog+映射幂等 |
| 原 resolution 表约束 | 只允许 §6 已验证的 v0.2 within_revision artifact 使用相同两端 bundle；Entity/Event link 两端的 (bundle,ref) 不得相同；外键与既有决定枚举保留 |
| canonical_catalogs.publication_sequence | 唯一递增 identity 列；最新 catalog 按此序列读取，不按事务开始时间 imported_at 判断 |

`chapter_store.py` 持有新章表的访问；catalog 继续由 canonical_store.py 持有。不改 0005 Reader Presentation 的 entity/event + Claim-only 约束，不复制 staged 实体表。source anchors 包含在 immutable artifact 中，索引是派生查询能力。接受入口先取得 producing-run identity，然后完整 artifact、chunk accepted pointer 与 completed 状态同一 fenced 事务提交；如果 run 已先提交，只能从其完整 request/response 重验收养。

复用现有 lease-fenced 短事务；模型等待期间不持 DB 事务。accepted run/状态提交间退出可收养已有结果，但须先重验原始 request/response、完整联合产物、source/plan/config fingerprint。失去 lease、错版本、hash 漂移、缺章、额外旧章、重复接受冲突都拒绝，不能重新调用模型后覆盖原审计。旧 fake executor 只允许明确的测试注入；生产缺 model/source 不得假成功。

## 6. 同书跨章与跨来源审核

新增 `chronicle.resolution-links / 0.2`，字段复用 v0.1，增加 `scope: within_revision|cross_source`。C0 历史 fixture 不重写。新执行路径的所有 resolution 使用 v0.2。

- cross_source：保留现有 builder 两端 bundle 不同的要求、blocking 和初始 uncertain。
- within_revision：新增 `build_within_bundle_candidate_set(bundle, chapter_by_ref)`；仅不同章、不同 ref，同类型稳定 surface 或既有 Event blocking 能产生候选。按 (chapter_index,ref) 确定左右端，去 self／对称重复；不增加模糊匹配或模型裁决。所有初始决定也是 uncertain。
- 新章内同一个 local ID 已共享，不能再为它生成自反合并审核。跨章名称相同不自动同一身份。
- 新 revision 的 staged↔staged 候选使用普通 `chapter_pair` 审核项，两端均标 staged，不伪装 published canonical，也不按名称做批量 fan-out。
- published canonical↔incoming 继续用 Amendment 0007 batch/default/group overrides。
- 一个版本化 frozen plan 同时覆盖上述两类：每个 (resolution_sha256,candidate_id) 恰好出现一次。恢复重用原计划，不能因新 catalog 擅自重排／重建。
- plan_version 固定为 c2r1-review-plan-v1。ReviewItem.kind 仍为 stage_gate，payload.scope 仍为 resolution；新增 payload.review_mode=chapter_pair|published_batch，不把新 mode 当数据库 kind。plan_fingerprint 是版本、job/revision、assembled hash、base catalog hash、全部排序的 resolution hashes/candidate keys/member refs/group IDs 的 canonical JSON SHA-256，排除 decision/status/resolved_at。同一新版本可以含两种 mode，不允许混入旧世代计划。
- resolve 在人审前持久化非公开 staged bundle 和 initial resolutions，满足外键和证据查询；publish 再校验并幂等复用。chapter_pair 的决定只 fan-out 到该候选，published_batch 仍按 default/override 精确展开。
- publication_v0 的版本门需窄适配接受已验证的 0.2/scope，union/负约束/UUID 规则不变。禁止临时降版为 0.1：关系 provenance 的 resolution hash 必须与持久化的原始 artifact 相同。
- 现有 C1 within_book_links 不再成为新章路径中“未送给 publisher 的隐藏 same-link”。跨章决定全部显式进入最终 resolution，冲突校验和发布消费同一图。
- Graph key 必须是 (bundle,ref)。同书链可能把两个 published IDs 间接连起来，提交时继续拒绝该桥接；not_same/related_occurrence 负约束及 Event 最终发布约束不削弱。

具体审核范围、证据 DTO 和连续交互由 [review-workflow.md](review-workflow.md) 统一拥有。

## 7. 发布和公开读取

`publish_chapters(conn, job_id, accepted_artifacts, assembled, final_resolutions, lease)` 复用 C0 publisher 和 persistence helpers。所有章及候选处理完成后，在一次短事务中重验／幂等复用 staged source bundle 和 resolutions，固定 catalog、每章 publication、catalog output 和 publish checkpoint/completed 状态。章节与 catalog 同时公开。

当前代码尚无统一 catalog 锁。本轮新增数据库内固定 key 的 transaction advisory lock，覆盖读当前 catalog、候选覆盖再校验、publisher 和全部公开写入。各 catalog 写入口使用同一锁；identity publication_sequence 在持锁写入时分配，所有最新 catalog 查询改按该序列。基线改变且产生新候选/冲突时返回 publication_plan_stale，保留旧审核计划和失败证据，不自动放行或重建冻结计划；需要重新规划的后续 job 不属于旧计划的成功恢复。锁等待不延续失效 lease，进入写入前仍须重验。

Publication 保存已 remap 且 canonicalized 的对象/事件引用，同时保留 source ref、原文 anchors 和 unresolved mention。已明确提交 uncertain 的两个候选可分别发布 singleton，但 UI 不能表示它们已经同一。

`publication_id` 是不可变阅读版本。本轮新内容版本来自新上传 revision；同 revision 的 accepted/已发布联合产物只允许幂等重放恢复，内容变更拒绝为 immutable_artifact_conflict，不新增生成世代或覆盖 source bundle。用两个 revision 验证旧链接固定旧译文和原文。目录显示 revision，不混合新旧内容，也不额外开发任意再生成或旧结果迁移。

公共路由：

下表是浏览器访问的Rust前端路径。Python sidecar内部使用对应`/v0/chapters*`，沿用现有公共router；server.py明确把配置的storage_dir注入source reader。不得新增第二套原文服务或让浏览器绕过Rust入口。

| 路由 | 返回 |
| --- | --- |
| GET /api/v1/public/chapters?limit=50&cursor=… | 已发布目录，书名/章名/顺序/revision/publication_id，稳定游标，next_cursor |
| GET /api/v1/public/chapters/{publication_id} | 完整 ordered translation blocks、来源概览、预先完成的对象/事件引用；不动态生成 |
| GET /api/v1/public/chapters/{publication_id}/sources/{anchor_id}?view=window|chapter&cursor=… | 该 publication 可见的精确原文和有界上下文；复用唯一 source reader |

目录排序按 document_id、revision_no、chapter_index、publication_id，cursor 绑定 query/版本；limit 1..100。详情必须完整返回或明确失败，不能以摘要/首段冒充全文；在此容量内响应不得超过 Rust 8 MiB 转发限额。原文窗口默认前后各 400 code points，整章分页最多 16,000 code points，返回 source hash、chapter 范围、page 范围、next_cursor、has_more，以及服务端切好的高亮 segments。

未发布、跨 publication anchor、未知版本均 404；输入错误 400；错误方法 405；来源缺失或 hash 漂移 409 source_unavailable/source_mismatch。绝不开放整个 Studio 上传目录，也不从 document 最新版补读。所有 GET 为只读，不调模型、不分配 canonical ID、不修复数据。

## 8. 最小阅读界面

公开导航中有“篇章”入口 → 书/章目录 → 单栏完整白话文。以正文为主，章标题、来源和引用入口次之。每个译文段可查看多个来源；关闭引用恢复触发位置，失败保留全文并允许重试。原文能从片段展开到整章，默认不常驻双栏。正文按普通文本渲染。

首轮可保存对象/事件关联并提供普通详情入口；不要求做正文事件悬停、时间轴重排或人物时态。空目录、加载中、404、请求失败要有明确状态；无完整译文时不能拿现有 Reader 摘要充数。

React 新组件可先不接 App 并行开发；修改生产入口的任务按顺序各自重建并提交 web/dist。不得先以过期 dist 通过一个 UI 任务，再把它的必要构建拖到后续任务。

## 9. 验收材料与结束条件

首选固定四章：同一《三国志》材料中的《先主传》《周瑜传》《鲁肃传》，加《资治通鉴》覆盖建安十三年附近的完整卷。前三章复用已提交固定 oldid 文本；第四章优先核对卷六十五的全文、版本与长度。语料任务记录实际 oldid、源 URL、下载/转换 hash、正文及嵌注边界。如果整卷超过容量，保留为明确拒绝样本，并选同书相邻且符合容量的完整卷；不能截取一小段充作一章。只在该任务完成时冻结实际第四章及替换理由。

《三国志》三章包装成一份可重建 Markdown revision，另一著作单独一份；验证同 revision 跨章，而不只测三个独立上传。每章原文件继续在 apps/chronicle 内受 Git 管理。追加小型人工构造用例只证明歧义／故障合同，不能冒充真实史料发现。

真实语料的逐章审阅覆盖：首尾和嵌注是否完整；“操／曹公”“瑜／公瑾”等指代；同名异人／异地；人物无直接 Claim；事件原文、时间和角色；前文主语/后文动作；跨章/跨书匹配；无法确认时保留 uncertain。至少 12 个带原文位置的核对点，结果区分真实史料观察与合成负例。

最终必须在新空环境经 Studio 上传、后台处理、人工审核、发布、浏览器阅读及原文核对，包含重启/接管、失败/修正、无部分发布、旧阅读版本不串线。先通过离线整链和当前 CI，再做真实 provider 和独立人工内容检查；脚本 PASS 不等于译文正确。已有 C1-T17 验收不重开，#541 仅作为回归发现来源。

每个执行叶按当前 [repository task-completion 流程](../../../docs/development/task-completion.md) 交付实现、验证和 PR。本轮最终门依赖各模块的实际输入与验收证据；任务状态由当前任务管理工具维护。
