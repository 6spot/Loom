# Chronicle 第三轮：人物阶段资料与阅读联动契约

状态：**R3 扩展目标**。C2-R2E 已实现按已审核阶段列举当时状态的基础链路；本合同中的任期推理、来源阶段算法及完整人物页仍由 R3 交付。父 Issue [#550](https://github.com/6spot/Loom/issues/550)，任务与文件归属见 [第三轮索引](../../../docs/tasks/chronicle/third-round/README.md)。

2026-09-12 交接：[source-corroboration.md](source-corroboration.md) 拥有共用结论、两次审核与综合叙事发布合同。主阅读定位为 `{version, paragraph_id, phase_id}`，来源 ReadingUnit 继续表示原书译文。本文的来源阶段候选与任期算法向共用事实核对提供依据，不能绕过审核另建历史真伪结论。§7 的来源 stream 路由是来源专用扩展，主阅读复用 history API；§8 使用紧凑状态和独立人物页，不再要求静态设计站或三层行为列表。

本文拥有人物状态的来源、阶段、明确性、审核和读取扩展。章节原文与联合产物的基础规则归 [chapter-production.md](chapter-production.md)，阅读顺序、定位和快照归 [continuous-reading.md](continuous-reading.md)，共用页面规则归 [reading-experience.md](reading-experience.md)。本文不把前两轮的实施目标当成已通过的验收。

## 1. 首版结果与范围

读者看到的是“这个人，在当前正在叙述的阶段，有哪些记载”。人物的 canonical 身份保持稳定；每项身份或关系独立带有依据和明确性。

| 区域 | 首版内容 | 时间含义 |
| --- | --- | --- |
| 当时身份 | 官职、爵号；明确记载的效力、归附关系 | 按当前阶段及证据取值，允许兼任和并存 |
| 地点当时状态 | 有据的行政归属、实际控制，二者分开 | 每个地点独占一行，不从人物到访推导控制 |
| 人物详情的经历与变化 | 授任、兼领、离任、辞还、归附、出使、参战等记载 | 放入人物经历时间轴，不占阅读页默认状态行 |

首批长期关系为 `serves`（来源明确的效力）与 `attached_to`（来源明确的归附／投靠），方向是“人物 → 对象”。对象可以是有来源的 person、polity 或 organization。一次投降不自动证明以后一直效力；授官者、官职名义归属与实际效力对象分开保存。

政治联盟暂保留既有 Event/Claim，不在本轮计算长期联盟有效期；亲缘、婚姻、师友图谱保持后续范围。人物详情须能介绍人物并按时间查看有据经历，不要求穷尽完整生平。已有原文记载仍保留，不删译文或 Claim。地点状态与人物状态一样依阶段显示；“参加某事件”不证明所在位置或领土控制。

只使用 Chronicle application-owned persistence 和产品 API，遵守 Amendment [0006](../../../docs/architecture/amendments/0006-application-owned-product-persistence.md)／[0007](../../../docs/architecture/amendments/0007-chronicle-resolution-review-subjects.md)。阶段不是 Loom World Time，状态投影不是 Runtime World Truth。此扩展未改变身份等价、canonical union 或已注册存储边界，不需要为应用字段另立 Loom Amendment。

使用新开发测试数据；不安排旧数据迁移、补写 immutable artifact 或双生产链。背景图上传／生成／关联沿用独立规划，不加入本轮。

## 2. 明确性：用户已确认的两档

| 对外标记 | 判定对象 | 呈现 |
| --- | --- | --- |
| 明确 | 本项结论及其在此阶段的适用性有已核对的来源支持 | 正常墨色，明确标记 |
| 不明确 | 有材料，但结论、任期、先后或来源分歧尚不能确定 | 较弱灰墨色，不明确标记，仍可读、可点 |

DTO 统一使用 `certainty=clear|uncertain`，分别对应“明确／存疑”，与综合结论一致；不再新增 `unclear` 枚举。标记属于每一项，而不是整个人物。使用“实心圆＋明确／空心圆＋存疑”的可辨识组合；紧凑处可将文字放入可访问名称和聚焦说明，始终有可查的图例。颜色不是唯一信号，不使用整卡 opacity 或 disabled 样式。D02 在正式组件中验证排版。

“明确”是有来源支持的当前显示结论，不声称解决了所有史学争议。限定语属于结论本身，例如“据某书”“自称”“奏章称已辞还”，不能藏在只有点开才知道的说明里。

必须分开三个量：

1. `extraction.confidence`：模型自报的抽取把握，不能换算为显示颜色。
2. 原始 Claim 的 `assessment.status`：沿用 [data-contract.md](data-contract.md)，初次抽取通常为 unassessed，原 artifact 不可覆盖。
3. 人物阶段资料的审核评估：对具体事实、阶段对应或先后依据的 supported／uncertain／disputed／rejected 决定，保存在版本化评估产物中。它不是人物合并决定，也不回写原 Claim。

发布前按下表编译；前端只渲染返回值。

| 输入与当前阶段 | 结果 |
| --- | --- |
| supported 的授任／在任记载，且 supported 的当前阶段绑定直接覆盖此处，无适用分歧 | 明确 |
| supported 的明确持续区间确实覆盖当前阶段，无适用分歧 | 明确 |
| 已能证明先前任职，但缺少继续有效的依据，且没有已证明的结束 | 不明确；“此前记载／任期未明” |
| 有可定位材料，相关评估为 uncertain／disputed，且材料可用于此阶段 | 不明确；保留具体原因及归属 |
| 某项已证明结束，或已证明尚未开始 | 不进入当时身份；需要时在相应阶段变化中查看 |
| 不知道一次记载在当前阶段之前还是之后 | 不把它作为“此前任职”或当前候选；按需显示“阶段未明确”材料 |
| 没有相应材料 | “暂无记载”；不是一条不明确的虚构身份 |
| rejected，或结构／引用不合法 | 不进入人物资料；保留非公开审计，结构错误阻止接受／发布 |

原因码至少包括 `tenure_unproven`、`order_unknown`、`source_disagreement`、`attribution_uncertain`、`evidence_uncertain`。返回稳定 code 和中文短说明；每项可有多个原因。“任期未明”与“来源分歧”不能被两档颜色抹成同一种问题。

## 3. 阶段与状态运算

### 3.1 阶段依据

阶段是来源支持的一段叙事语境，以章内 local phase ref 表示；公历年份可以未知。同年内“授任前／后”“转投前／后”可不同，前提是有原文支持其先后。

整章产物给出阶段、阶段先后依据、每个译文 block 的阶段绑定。程序保留原 Event.time，不新增历法转换器。只有已验证且可比较、不重叠的日期范围可以证明跨章先后；同年、同月、同一 canonical Event 或相邻正文序号本身都不能证明严格先后。

明确的来源内先后边形成无环偏序；算法只使用 supported 的边。未知／有分歧的先后不进入确定顺序。跨来源不因同名事件、日期接近或别名相同直接接边。模型不能引用尚未提供的其他章 local ID。

每个 ReadingUnit 增加的阶段绑定区分：

- `single`：一个有依据的当前阶段；
- `process`：本段确实经历多个有依据且有序的阶段；保留全过程；
- `ambiguous`：存在多个解释，无法唯一确定，分别呈现材料；
- `unknown`：不能定位阶段，不沿用上一段。

上述多阶段绑定用于原书译文。综合正文每段只有一个已审核主阶段；多次任命涉及状态变化时另起自然段，不能只取最后一个身份代表整段，也不能直接将来源 unit 的 process 作为一项当前状态。模型仍以完整自然章联合生成；不追加逐句定位或逐句翻译要求。

旁及旧事、预叙或打开预览不切换当前阶段；真正回到早年叙事时切换。阶段绑定须与第二轮 current_event_refs、叙事／旁及区分相容；不能用正文中所有事件的时间当当前时间。

### 3.2 事实与操作

每条人物状态事实都要指向已有 Claim、人物和具体值：

| 维度 | 值 | 首批动作 |
| --- | --- | --- |
| office | 有来源的 office Entity | start、end、attest |
| title | 有来源的爵号 Entity（现有 other 类型，由 state dimension 指明用途） | start、end、attest |
| affiliation | serves／attached_to ＋目标 Entity | start、end、attest |

office/title 的值不是人物身份；不要把“某太守”当作该人物 canonical ID。授予者和官职名义所属可选，但填写时各自必须有证据，不能由朝代常识补全。

`start` 是来源支持的取得／归附，`end` 是具体项的结束，`attest` 仅证明在所指阶段有此记载。每条另存 `qualification`：ordinary／recommendation／self_designation／posthumous／reported。推荐与追赠不能建立生前当前任职；首版将它们作为限定的本段记载，操作仅 attest。自称只证明“自称某号”，不得去掉限定语。引述的辞还只表示该来源中的自述，不自动证明朝廷收讫或其他来源也承认。

不同官职、爵号、关系可以并存。取得新职位不清空其他项，转投只结束有证据对应的关系。状态键由已确认的人物 ID、维度、值／对象 ID、关系及必要限定组成；不得靠显示名称、官阶高低或“通常不能兼任”覆盖旧项。

结束仅影响相同且身份映射已确定的状态键中、可证明早于结束的授任／观察。之后再次授任可以形成新一段任职。值的身份未确认或先后不足时保留不明确，不按同名标签强行关联。跨章、跨来源保留每条事实的 provenance；人物同一不等于主张同一。

明确持续区间必须另外有来源支持，边界采用包含起点、不包含已知结束阶段。仅有 start 而无 end 不产生无限明确区间。纯编译器可把已证明早于当前阶段的记录列作“不明确的此前记载”；不能把无法比较的记录、已知未来或已知结束项混入。

### 3.3 来源分歧

主阅读的人物资料消费综合版本已审核结论，多份来源可互补并保留归属；来源阅读的资料才围绕该 stream 的原书记载。不从另一来源补上未来头衔，也不在读取时重新判定真伪。

不同官职、不同阶段或不同效力对象不自动构成矛盾。只有有依据指向同一个问题和可比较阶段的不同主张，才由审核记录为分歧。不得比较模型 confidence 或导入时间选“赢家”。

跨来源分歧链接绑定审核时的 catalog、双方的 source Claim／状态事实和阶段适用依据。新发布可增加新的不可变分歧索引；旧版本结果不改变。综合正文的状态和分歧已经固定在 publication version 中，不叠加最新 catalog 的提示；新判断经重新审核发布新版本。

分歧索引只能增加已记录的解释和不明确原因，不能单独把原先不明确的旧来源提升为明确。重新核定内容走新 revision／发布，沿用已有不可变版本规则。

## 4. 0.3 整章联合产物与模块边界

在第二轮 chapter-candidate／artifact 0.2 基础上增加 `person_states`，形成 0.3；保留完整译文、阅读注解、C0 bundle 和同一组来源锚点。C0 Entity/Event/Claim schema 和 Resolution 0.2 语义不变。

| 新字段 | 必须表达 |
| --- | --- |
| phases[] | local phase_id、简短来源标签、event_refs、source_selections；不自行发明日期 |
| phase_orders[] | local assertion_id、earlier_phase_ref、later_phase_ref、来源依据 |
| unit_phases[] | 每个译文 block 恰好一条绑定；mode、phase_refs、source_selections |
| facts[] | local fact_id、person_ref、dimension、value_ref 或 relation/target_ref、operation、qualification、phase_ref、claim_refs、source_selections、attribution |
| continuities[] | local assertion_id、对应状态事实、开始／结束阶段、明确持续的来源依据 |
| disagreements[] | 本章明确记录的不同主张与相关事实 refs；来源归属和阶段依据；不填外部 canonical ID |

所有 local refs 使用带 kind 的引用，在同章内闭合；多态 object 不用任意字符串代替 ref。attribution 区分 narrator／quotation／annotation／hearsay，保留已有来源名和叙述者材料。仅可把模型返回的解释当候选，不允许模型直接返回 supported、前端 certainty、canonical UUID、stream/unit ID 或 URL。

phase/fact/continuity/order 等可审核条目使用彼此不混淆的 ID 类型；unit phase binding 的审核 ID 由程序计算。每章最多 512 个 phase、512 个 state fact、1,024 个先后／持续／分歧依据条目，每 unit 最多 8 个阶段；超出整体失败并报告容量，不静默删去条目。仍受第一轮 prompt／response／provider limits 约束，不新增独立模型轮次。

纯模块接口由 T01 变成 Python/TypeScript 的共享机器契约：

- `validate_person_state_candidate(request, candidate)`：结构、引用、类型、来源选择器、unit 覆盖、phase 图及与 reading 的一致性。
- `remap_person_state_evidence(chapter_artifacts, revision_ref_map)`：同一 revision namespace，保留 origin chapter/local refs 与 hash。
- `compile_person_state_projection(evidence, assessments, canonical_map, reading_manifest)`：只使用已核对的事实／时间依据，输出不可变 unit 人物摘要、完整状态条目、变化和诊断。
- `compile_person_state_disagreements(base_index, reviewed_links, catalog_membership)`：为新 catalog 编译有界可索引的来源分歧链接。

以上纯函数无 DB、网络、模型调用、UUID 分配或系统时间。输入相同输出与 hash 相同，数组排序规则进入 schema/fixture；不得按 dict 遍历顺序随机生成结果。`person-state-contract / 0.1` 与编译器版本进入 fingerprint。

### 4.1 共享机器契约与固定 fixture（T01 冻结）

T01 把上述约定固化为可被各模块直接消费的机器契约，避免实现中自定状态语义：

- 模块：`apps/chronicle/persistence/person_state_contract.py`、`apps/chronicle/webapp/src/lib/person-state-types.ts`、`chronicle-person-state-v0.1.schema.json`，以及 `chronicle-chapter-candidate-v0.3` / `chronicle-chapter-artifact-v0.3` schema；契约版本为 `person-state-contract / 0.1`。共享 schema/types/runner 只由 T01 修改；后续新增字段回此契约统一处理。
- 同一份 JSON fixture：`apps/chronicle/ingestion/fixtures/c2r3-contract/`（`request.json`、`candidate-valid.json`、`artifact-accepted.json` 及正反例、公开/审核 DTO 例）。#622 输出、#626 生产接线、#627 只读查询共用这一份，不各自另建第二套状态、来源或发布路径。
- 来源 phase 与综合 phase 是不同空间：只有带原文依据的明确关联才可映射；没有关联时保留未知或交回核对，禁止按年份、同名事件或段落序号猜测对应。
- 来源的 supported 只评价该条证据，不能绕过既有 facts/prose 审核变成公开的 clear 结论；综合状态最终来自固定 publication version 的已审核结论。
- 明确性由编译器按审核评估计算（`clear | uncertain`），模型 confidence 不参与显示判定；`recommendation` / `posthumous` 只能 `attest`，不建立当前身份。地点行政归属与实际控制分开，原始 Event 不自动成为锚点、也不能凭到访推导控制。
- 候选键由程序按 kind、chapter、item_ref 与已解析锚点计算；审核决定 payload 必须携带 `plan_fingerprint`，跨版本/并发冲突为 409 且不丢草稿。

T02 扩展现有 chapter_prompt／chapter_extraction／model_provider；整章一次联合生成加最多一次完整章修正，完整采用已有 request/run/fingerprint/运输重试。结构验证不证明模型读懂原文；语义评估和真实语料验收分别负责这两层证明。接受的仍是一份完整联合 artifact，没有独立人物状态补生成或阅读时生成路径。

## 5. 阶段依据审核

首版选择**每个自然章集中审核一份阶段依据包**，包内按人物列出变化链，共用阶段依据单列。不是每个阅读段落创建一个 ReviewItem。此为本轮实施选择；身份合并的已有审核规则保持不变。

状态事实、阶段对应、先后／持续和分歧依据均有稳定候选键。一个候选键在该 frozen plan 恰好覆盖一次；批量操作只是记录操作者对这些具体候选的评估，不建立人物等价。

复用同一 job 的 resolve 阶段、stage_gate ReviewItem 和连续审核外壳：

1. 完成已有身份 Resolution 审核，保留其原 frozen plan。
2. 以 accepted artifact hashes、assembled hash、最终 Resolution hashes、base catalog 和全部状态依据键生成 `c2r3-person-state-review-plan-v1`；来源外对照只能来自这个 base catalog。
3. 以 `payload.scope=person_state`、`review_mode=chapter_state_evidence` 冻结每章包；恢复 adopt 同一计划，不重生成模型内容，不重开已完成的身份审核。
4. 人工可批量确认 supported，或提交 uncertain／disputed／rejected，并按候选键给例外和理由。缺材料不能通过一次点击补成有依据；错误主体／引用只能拒绝或重做新内容，不能在表单里更改 immutable 原文或 canonical ID。
5. 所有本 job 待审核项均有终态后，发布编译器使用不可变评估产物。未审条目不得默认 supported；明确提交“不明确”可以发布。“暂时跳过”仍只改变浏览会话并继续待审。

supported 只确认该证据条目的语义；一个“明确授任”审核通过后，晚期在任仍须另有适用依据。因此不能用“整章确认”把所有后续阶段染成明确。审核申请将预测的当前／此前／结束效果与所用依据一并显示。

证据包展现人物、变更前后、各项适用阶段、授任或关系对象、原文片段和可展开整章；引述／裴注保留标签。批准默认值前能查看全部候选和例外数量。内部 hashes/refs 只在审计详情出现。

评估保存采用当前 job 锁和短事务，校验 review_id、plan_fingerprint、完整候选覆盖、允许的评估和例外；版本／并发冲突为 409 且不丢草稿。decision/status/audit 一并提交，不先标 resolved 再补明细。被显式 dismissed 的状态依据只可按 uncertain 处理，绝不成为 supported。

### 5.1 复用审核 API

在现有 `/api/v1/studio/jobs/reviews` 添加 `review_scope=resolution|person_state|all`。**省略该参数保持 `resolution`**，即当前未显式筛选的审核入口继续包含综合 facts/prose（narrative）；不得因为新增 person_state 而让既有综合审核项消失。第三轮页面明确请求 `all`，`all` 覆盖 resolution、person_state 与 narrative 三类。`link_kind` 仅用于 resolution，和 person_state/all 混用返回 400。issue#625/#628/#631 消费本已固定合同，不各自决定默认范围。cursor、open_count、URL、草稿隔离、候选类型、计数与再扫描均绑定 review_scope，且决定 payload 保留 scope。

审核前后端由 T01 的 `person_state_contract.py` / `person-state-types.ts` 提供同一份 scope 语义（`normalize_review_scope` / `review_scope_covers`），不各自实现默认值。

详情、contexts、sources、decision 沿用现有 routes，根据 frozen payload.scope 分派：

- 状态 detail 返回 `chapter_state_evidence` 数据；contexts 可按 candidate_id 分页，不能把所有身份候选的第一个片段当状态依据。
- 原文读取复用同一 source_context reader，校验 anchor 属于该包及其 frozen 对照成员；公开读取另外校验发布可见性。
- decision 的状态分支为 `{plan_fingerprint, default_assessment, overrides:[{candidate_id,assessment,rationale}], rationale}`；身份分支继续使用原 allowed decisions。服务端拒绝串用。
- 混合队列保留 `scope` 判别字段和有界 summary。未知提交结果、两 tab 冲突、保存并下一项、页尾扫描等继承第一轮行为。

## 6. 存储、发布与一致性

唯一新迁移 `apps/chronicle/persistence/migrations/0009_chronicle_person_states.sql` 由 T05 所有。连接仍为 CHRONICLE_DATABASE_URL；不访问 Loom 数据库。

| 持久化内容 | 归属 |
| --- | --- |
| 评估 artifact | hash、frozen plan hash、精确候选决定及审计引用；原 accepted artifact 保持不变 |
| stream 人物状态 manifest | stream、chapter publications、assessment hashes、compiler version、manifest hash |
| unit 人物状态索引 | stream/unit/person、来源事实键、阶段分组、明确性／原因、摘要和完整条目索引 |
| catalog 分歧索引 | catalog hash、双方事实的来源绑定、适用阶段依据和分歧理由；不可变、可分页 |

采用 product tables/indexes，不复制原文、完整译文、Entity/Claim 表或 job 状态机。物理表名与索引由 T05 按上述键实现；API/前端不依赖表名。

沿用唯一 catalog advisory lock、publication_sequence、lease fencing 和 chapter/reading publication 事务：catalog、章 publication、reading stream/index、人物状态 manifest/index、本 catalog 分歧索引与 publish checkpoint 同时提交。编译、模型等待或人工等待不持长事务；提交前重验全部输入、决定、catalog 和 lease。

任一章缺 0.3、评估遗漏、键映射不完整、图矛盾、hash 漂移、未知状态值或投影超限，整个本次发布失败。相同 artifact/评估/映射/编译版本重放返回已有结果；不同 payload 不覆盖已有 stream。恢复复用 accepted 内容和审核结果，不能再调用模型“修一份”。

分歧索引可以持久化不可变 manifest 与对受影响事实的索引，无需为每次 catalog 复制所有旧 stream 正文／单位。查询只做对当前 unit 的已编译资料和对应 catalog 分歧记录的有界组合，不执行历史推理或修复写入。

## 7. 公开读取

主阅读直接消费 `/api/v1/public/history/paragraphs?version&at|start&limit` 的实体及状态；结论依据使用 `/api/v1/public/history/conclusions/{id}?version`。R3 扩展按版本／段落一次有界读取主要人物与地点，沿用 `history-api.ts` 的公共类型和错误规则。缓存、详情、往返都固定 `{version, paragraph_id, phase_id}`；不因同年或同一事件猜测来源 unit。当前列举状态的实现不能冒充下面的专门任期算法已经交付。

下列两个计划中的 product GET 仅属于**来源阅读**，不作为主历史页的接口替代。浏览器经过 Rust，Python 使用对应 `/v0/*`：

| 路由 | 结果 |
| --- | --- |
| /api/v1/public/reading-streams/{stream_id}/units/{unit_id}/people?catalog=&limit=6&cursor= | 当前 unit 人物的阶段摘要；与 context_entities 的人物集合一致，按第二轮顺序分页 |
| /api/v1/public/reading-streams/{stream_id}/units/{unit_id}/people/{person_id}/states?catalog=&section=identities\|changes\|evidence&phase_id=&item_id=&limit=20&cursor= | 对应人物在本段的状态、变化或一项的完整依据；按需翻页 |

请求中的 stream/unit/catalog 组合必须有效；person 必须属于本段 context，phase 必须属于本段绑定。未知或错配为 404；参数、重复键、错 scope cursor 为 400；已发布内容内部不一致显式返回 409，不能补读最新资料。source 文件缺失／漂移沿用现有错误。

摘要每人最多预览 3 项身份和 3 项变化，只内联显示字段及依据数量／入口，必须返回各自总数／完整入口；不把首批冒充全部。主要人物默认最多 6 位，其他按需加载。人员 limit 1..50，详情 limit 1..50；summary/detail 每响应上限 128 KiB，按完整项提前停页并返回 next_cursor，不能截断结论。完整条目与第一批依据的编译大小上限为 64 KiB，超出在发布前拒绝。

identities/changes 只返回本段适用资料及本段经历的变化，不把未来生平装进默认展开区。phase_id 可筛选本段的一个阶段；省略时返回有序阶段分组。详情每项预览最多 16 个 evidence descriptors，并返回 evidence_count/evidence_cursor。section=evidence 要求 item_id，cursor 绑定该 item、原 section、phase、stream/unit/person/catalog/manifest；此分支每页最多 50 个描述符，不再返回其他状态。错配及混用无关参数为 400，非本段条目的 item_id 为 404。

每份 DTO 包含 stream_id、unit_id、chapter publication_id、catalog_sha、state_manifest_sha、phase_mode/phase summaries。条目含稳定 item_id、person_id、dimension/value/relation、qualification、certainty、reasons、source fact/Claim 归属和来源入口。API 只组合已编译结果；UI 无“根据状态字段猜颜色”的第二套逻辑。

原文仍通过已存在的 `/chapters/{publication_id}/sources/{anchor_id}`，包括分歧另一方所属的 publication。每个 descriptor 指向自己的版本，不把别书锚点套到当前章。事件入口继续调用第二轮同一 snapshot 的 preview/targets。

catalog 绑定探索范围、身份成员映射与分歧索引；stream/章 publication 固定内容与自身状态投影。任何缓存和 cursor 都包含相应版本，旧快照重复读取得到同一结果。用户明确换新 catalog 才看见该快照新增的来源分歧。没有阶段资料与加载失败分别表达。

## 8. 阅读与审核界面

沿用正式 HistoryPage 的左轴、中正文、右栏布局与窄屏“人物地点”入口。右上为当前及邻近重要锚点，右下为当时人物、地点；不把锚点标题插到正文，不为每个人再开一列。D02 使用正式组件及明确标注的测试场景验证桌面／窄屏交互，不新建静态设计站。

人物默认一行显示姓名、当时官职／爵号／效力；地点默认一行显示名称及行政归属／控制状态。兼任并列，不压成“最高官职”。出使、参战、进入荆州等行动进入人物详情的经历时间轴，默认侧栏不显示行为摘要。只列主要人物、地点；其他人物可通过搜索进入详情。无新阶段不弹 toast、不闪动。

不明确条目使用灰墨色及空心标记，hover／键盘 focus／触屏点击均可查看原因和来源。来源不足不是禁用按钮；“暂无记载”与“阶段未明确”是不同空态。保留语义限定语、焦点、44px 触控范围、WCAG AA 文本对比度和 reduced-motion，复用第二轮的来源面板、事件入口及返回行为。

人物预览接收相同的阅读 locator 和阶段条目；不能用最终称号填充“当时身份”。官职、关系对象和政权名称也取有阶段依据的来源表示，不用后来的国号回填早年。独立人物详情提供简短人物介绍、有据经历及身份演变时间轴；从主历史进入时保留阶段与原段返回入口，直接进入则展示人物整体情况，不擅自选定当前年份。此人物页仍是 R3 待实现项。

现有 useReadingPosition 仍唯一拥有 active paragraph／unit 和导航。第三轮只订阅该 locator，按段一次取得人物摘要，不为每个人发一次状态请求，也不扫描全世界。综合正文查询 key 至少包含 version／paragraph；来源阅读另用 stream/catalog/publication/unit。相同 key 合并并发，最多缓存 100 个位置或 2 MiB，LRU 回收。详细项与原文只在用户打开时请求。

切换段落时使用新段人物、地点及其状态，将未取得的阶段资料显示为加载中；不短暂沿用上一段身份。迟到响应不能覆盖当前段；悬停旧事不触发切换。back/forward/刷新/跳转/返回都按同一 locator 查询，不在前端累计或撤销历史状态。

Studio 复用固定操作区、草稿隔离和 source viewer；状态表单可以独立开发，最终由统一页面接线任务挂接。共享 App/router/typed client 接线、build 和 web/dist 写入均指定串行所有者。

## 9. 验收与可交付顺序

现有固定原件足够启动：`corpus/first-round/sources/` 下《周瑜传》《先主传》《鲁肃传》《资治通鉴卷六十五》。第三轮语料包只增加案例索引、预期与来源 hash，不复制或截短成假整章。

| 真实材料核对点 | 必须证明的行为 |
| --- | --- |
| 周瑜“授建威中郎將” | 授任结论、授任者和阶段有各自依据 |
| “權拜瑜偏將軍，領南郡太守” | 两个并存项分别显示；不拿它们覆盖此前阶段 |
| “瑜為前部大督” | 检查本次行动角色和长期任职的区别，不自动永久继承 |
| 刘备“先主遂去楷歸謙” | 正确主体及田楷／陶谦，定向关系及各自变化 |
| “上還所假左將軍、宜城亭侯印綬” | 保留奏章自述限定，只处理对应官爵，不结束所有关系 |
| 周瑜篇开头“皆為漢太尉”“父異，洛陽令” | 不把祖辈／父亲官职赋给周瑜 |
| 裴注、引书、正文中不同说法 | 保留来源归属，不能仅因晚导入就覆盖 |

D01 至少冻结 16 个逐项可复查案例，真实材料必须可重定位；缺少明确结束／同年未知顺序等真实样本时用标明 synthetic 的反例。候选核对点不是已经核准的完整生平表。

自动验收覆盖：完整章生成与修正、全部引用和 remap、阶段偏序、未知年月、同年不同阶段、兼任、针对性结束、再次授任、推荐／自称／追赠、引述归属、无依据空态、分歧、跨章同人／同名异人、未来泄漏、部分发布／lease／恢复／stale plan、固定快照、混合审核队列和阅读导航。

浏览器证据使用 1440×900、1024×768、390×844、320×568、200% 缩放、键盘和触屏。延续第二轮的窗口和性能预算；已取回数据后当前人物区更新 p95 ≤100ms，单段初始状态获取不按人物数产生 N+1；错误不清空正文或偷换阶段。不能用源码字符串、仅 HTTP mock 或截图替代应由真实栈证明的行为。

整链 gate 扩展第二轮的同一个 lifecycle 支持，提供 `acceptance/third_round_gate.py --mode fixture|live --env-file PATH --source-pack PATH --evidence-dir PATH`，不复制部署入口或直接写 DB 来伪造发布。fixture 证明机制；live 使用真实 provider、完整自然章、Studio 人审／发布与独立内容核对，记录具体 publication/stream/catalog/原文锚点和逐案结果。

本轮有三个可评阅节点：D01/D02 的真实样例与界面设计；T08/T10 的生产、审核和读取契约；T13–T15 的页面接线、自动门与真实内容验收。前两轮的真实验收问题仍按各自 Issue 处理，设计／fixture 通过不能替代这些结果。

独立组件复用第二轮 reading-component-smoke runner。T01 注册 `--suite r3-harness|person-states|person-state-review|r3-all`，T11/T12 分别拥有自己的 scene/spec；r3-all 缺任何组件场景必须失败，原第二轮 suite 范围保持独立。新 suite 的参数继续使用 `--base-url` 和 `--output`，不另建 Vite/浏览器生命周期。

实施后的具体运行步骤由 T14 写入 `person-state-acceptance.md`；本节只固定验收合同，不建立第二套 runbook。任务状态由当前任务管理工具维护，任务文档保留需求、接口、文件边界和验收，交付遵循当前 repository completion workflow。
