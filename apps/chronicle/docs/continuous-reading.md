# Chronicle 第二轮：连续阅读数据与导航契约

状态：**已拆分的实施目标，尚未实现**。父 Issue [#549](https://github.com/6spot/Loom/issues/549)，执行与文件归属见 [第二轮台账](../../../docs/tasks/chronicle/second-round/README.md)。第一轮 [章节契约](chapter-production.md) 仍独立交付；下述 0.2 扩展由第二轮任务负责。

## 1. 阅读组织与权限

一条 Reading Stream 对应一个已发布 document revision，按 chapter_index 和译文 block 顺序连续阅读。全部章、全部正文都可到达；正文不按事件年份重新排序，不截取若干 Claim 冒充完整内容。章间有标题与来源分隔，同章原有指代及嵌注归属保持连续。

跨来源通过同一已确认事件的“其他记载”明确切换到另一 stream，并保存返回位置；不在前端自动混编多本书，也不额外生成跨书历史文章。既有 `/timeline` 继续承担按年浏览事件的入口，增加“进入相关正文”；侧边轴负责定位当前叙事中的时间区段。倒叙章或下一篇传记可以回到较早年份，轴明确显示回溯而不把文字重排。原章阅读入口和完整古文引用继续可用。

阅读时间、片段与索引均为 Chronicle application-owned projection，遵守 Amendment 0006。模型、名称、展示分组不会新增 canonical 身份等价；既有 Resolution / Amendment 0007 决定不变。人物长期官职、阵营、关系有效期、地图、Why、问答与模拟不在本轮。当前片段的事件角色不成为长期状态，事件地点不证明参与人物都在当地。

使用全新测试环境。第一轮产物和检查保留为独立交付证据；不迁移旧数据、不补写旧 immutable artifact、不运行新旧两套生产链。没有第二轮注解的历史 fixture 可以继续经过原来的局部回归，但不冒充具有连续阅读能力。

## 2. 第一轮缺口与 0.2 联合产物

第一轮有 translation.blocks、原文 mentions、source anchors 和对象/事件 refs；尚无精确译文事件词位置、主叙事/回溯区分及每段阅读时间。第二轮新增 `chronicle.chapter-candidate / 0.2` 与 `chronicle.chapter-artifact / 0.2` schema，复用第一轮全部字段及校验，并增加 `reading`。C0 staged schema 和 Resolution 0.2 不变。

0.2 仍在一次完整章联合翻译/抽取中生成；最多一次含同一完整章的修正，沿用第一轮容量、运输重试、fingerprint、租约和 run 审计。不是逐段调用，也不是访问页面时再做语义标注。0.2 的每个译文 block 最长 8,192 Unicode code points，超过时在同一次整章输出中自然分段。该限制不授权删文或分段独立翻译。

展示段落在明确的叙事时间/行动转换处自然换段，通常为 80–500 个汉字；长引文可更长，不机械截断句子。不要为减少注解把整章塞进一个 block，也不把可正常区分的所有阶段一律标为 mixed/unknown。分段仍在同一次整章生成中完成；真实内容门检查有明确时间依据的段落是否被正确标注，而非只检查字段存在。

`reading.units[]` 必须与 translation.blocks 一一对应、同顺序、无遗漏或重复。模型只返回 block_id 和 source-local temp refs，不返回 canonical ID、stream_id、unit_id、坐标或 URL：

| 字段 | 模型输出及约束 |
| --- | --- |
| block_id | 本章已有译文 block |
| narrative_time | `{mode: events\|inherit\|mixed\|unknown, event_refs: [], from_block_id: null\|id, source_selections: []}` |
| current_event_refs[] | 本段正在叙述的事件；不是出现过的所有事件 |
| event_spans[] | `{span_id, selection:{quote,occurrence}, status, target_ref, candidate_refs, relation, source_selections}`；selection 在当前**译文** block 内，occurrence 从 1 起 |
| context_entities[] | `{entity_ref, importance: primary\|other, source_selections, event_roles:[{event_ref,participant_index}]}`；来源必须支持本段涉及该对象 |

event_spans.status 为 resolved / ambiguous / unresolved：resolved 唯一 target_ref；ambiguous 无 target_ref、至少两个有效候选；unresolved 无 target_ref。relation 为 current / retrospective / foreshadow / background / uncertain。resolved 仅表示这次指代已绑定具体 source record，不宣称跨来源所有同名事件同一。译文写出“赤壁之战”时可以引用本章已有、有来源支持的事件，不要求古文出现同样四字；不能拿显示名称去查找任意 canonical Event。

每段最多 64 个事件 span、128 个 context_entities；span/context 及非 unknown 时间的 source_selections 为 1..16，unknown 时间为 []。current_event_refs、span 的 target/candidate refs 必须在本译文 block.event_refs 中；时间 event_refs 必须属于 current_event_refs。事件关联的全部 source-local refs 必须闭合。source_selections 复用第一轮 block/quote/occurrence 选择器，允许依靠同章其他段的证据；原文与译文的选择器必须用不同字段/类型。

时间规则：events 至少有一个 current_event_ref，取这些**来源表示自身**的 Event.time；inherit 仅可指向同章前面的一个 block，必须有原文承接依据，链最终到已知 events，不能跨章/成环；unknown 不带事件或继承；mixed 显式列多个当前事件的观察，不能用最早/最晚年份合成唯一时间。事件自身没有可用时间时保留 unknown。回溯/预叙/background span 不参与 narrative_time。模型不另外编造公历时间。

程序完成校验：原文选择器有效；译文 quote 按 code point 精确匹配且 occurrence 存在；span 不交叠（相同目标重叠也拒绝）、不能改写正文；context entity 必须出现在本 block.entity_refs 或当前事件明确参与者/地点中；event_roles 索引必须指向同一 entity 的原始 participant，role 值由程序复制而非模型重写。places 类型从 Entity record 确定。结构校验不证明“主要性”或主叙事判断正确，真实内容门必须独立核对。

artifact 增加解析后的译文 span 与阅读注解。ID、code-point 范围、hash、producer/request 绑定由程序计算；用带 kind 的统一映射 remap 到 revision refs，再按本次 catalog 映射到 canonical IDs。译文原文、引用与阅读注解作为完整联合产物接受，失败不得只发布其中一部分。

## 3. 阅读单位、时间分组与来源精度

一个 ReadingUnit 对应一个完整译文 block。`unit_id = ru_ + sha256(canonical_json(revision_id, chapter_id, block_id, artifact_sha256))[:24]`，检测碰撞；ordinal 在 stream 中从 0 连续递增。单位保存 publication_id、chapter/block 标识、source anchors、自己的 context 与 event spans。public DTO 提供程序切好的普通文本/事件 span segments，拼接文本必须逐字等于原译文；浏览器不使用 replace、innerHTML 或 UTF-16 偏移猜测事件词。

叙事时间输出原始观察、status 和独立的 display/grouping 字段。分组由发布前的纯编译器计算，API/浏览器复用结果：

- 仅合并**连续**且同一实际时间精度/历法分组 key 的 units；不把隔着别的时间再次出现的 208 年全局合并。group_id 绑定 stream 中第一个 unit 和 key，不随分页改变。
- 年级相同时只显示一次年标题；同年同月共享月标记；换月仅新增月标记，换年再显示年。日期仍保留在本段时间详情，不因共用月标记丢失。分页边界携带现有 group_id / continues_previous，不重复造标题。
- 年份已知、月份未知的单位使用单独的“该年，月份未明确”区段，不能继承附近已知月份。整段未知显示“时间未明确”，不能默认 208 年或静默沿用上一段。
- 年号/传统历月与经过 exact 转换的公历月分属不同 key。`year_only` 的八月只能显示为史料历法八月，不能变成公历八月；年号、era_year、月份及转换状态保留。季节和不可精确解释的原始日期保持 source label，不推算月日。
- 现有 source_calendar 没有完整闰月表达。含“闰/閏”或无法区分的原始日期按 opaque source label 保留，key 包含原始时间文本，不与普通同号月份合并；本轮不增加历法换算器。
- approximate、range、mixed、unknown 不与精确年/月混成同一区段。现有单个 normalized.year 不能被扩成虚构的 range endpoints。多来源对同一事件记年不同，预览显示分歧，不把它说成持续若干年。
- 当前段用本来源观察，不用 canonical Event 的聚合最小/最大年份代替叙事时间。传统日期只在现有转换合同验证成功时获得 normalized 字段。BCE/CE 沿用来源支持的年表示，不在前 1 年和公元 1 年间插入“公元 0 年”；无约定的 0 不生成精确标签。

同一 stream 的章边界是可见内容边界，不自动继承上一章时间；两侧各自明确且相同的分组可以连续。切换 stream 必须显示来源切换，不能延长原 stream 的轴体。轴反映叙事顺序，其长度按内容段落布局，不暗示等比例历史年距。

编译器固定输出 year_key、period_key、year_label、period_label、precision、observations 和 continues_previous。exact 公历 key 使用 `(gregorian, year, month-or-null)`；只有年份时 month=null 且 label 明确。未换算传统历使用 `(regnal, era, era_year, month-or-null, season-or-null)`，缺 era/year 则转 opaque；source key 不与 Gregorian key 相等。opaque key 包含原始时间文本及其 source calendar 字段；unknown 使用固定 unknown key；mixed/range key 包含完整排序后的不同观察及状态。approximate 进入 key。相同月份的日字段保留在 observations 而不重复创建年/月标题。year_key 包含历法与 era/year，year_key 未变时不重印年标题；period_key 改变才新建轴区段。所有 key 先 canonical JSON 再 hash，不能用本地化 label 作为身份。

## 4. 不可变发布与存储

新增唯一 `0007_chronicle_reading_streams.sql`，归本轮存储任务所有。复用第一轮 chapter_artifacts / chapter_publications，不另存一份正文、原文、对象表或模型 run：

| 表 | 责任 |
| --- | --- |
| reading_streams | stream_id UUIDv7、唯一 revision_id、origin_catalog_sha、manifest_sha、按顺序的 chapter_publication IDs、unit/group 总数及不可变 manifest |
| reading_units | stream_id + ordinal、唯一 unit_id、publication_id/block_id、已编译注解和文本 hash；正文读已有 chapter publication |
| reading_time_groups | stream_id + group ordinal、group_id、first/last unit ordinal、精度和显示字段 |
| reading_event_occurrences | stream/unit/canonical_event/span 或 current-event 标记、relation、来源 ref；供精确反查，不按标题建关联 |

全部表在 Chronicle 已注册 persistence 范围内。外键和唯一约束阻止跨 stream/unit、重复 index 和不存在 publication；一个 revision 只有一个不可变 stream。对同输入重复发布返回已有 ID，任何 manifest/hash/映射不同显式冲突。

在第一轮已建立的唯一 publish 短事务及 catalog advisory lock 中，完成 canonical catalog、全部章 publication、阅读 stream/units/groups/occurrences 和 publish checkpoint。任意错误回滚全部；租约过期者无权提交。没有新的 worker/queue/present 生成阶段。新 metadata 已并入 accepted artifact，恢复直接重验采用该 artifact，不额外调用模型。所有 expected 章均有 0.2 注解才发布 stream；缺章、混版本、拼接后正文 hash 不符、悬空引用、编译失败均阻止本次发布。

## 5. 固定内容版本与探索快照

stream 固定一个上传 revision 的全部章 publication。新 revision 是新 stream；旧 URL 继续读取旧正文与锚点。

探索范围另由 `catalog` SHA 固定：首次没有 catalog 的公开入口只解析一次最新 publication_sequence，并在响应中返回 snapshot；后续翻页、预览、事件目标和 URL 都显式带它。cursor 内也绑定它。读取仅包含该 catalog payload 明确覆盖的 refs，以及不晚于该 catalog publication_sequence 的 streams；禁止用全局 representation 表直接混入后续发布的成员。catalog 级不可变 payload 是成员依据，时间序列只是范围上限。

这样，同一快照下的两个来源可相互跳转，后台新发布不会改变正在阅读的分页或预览。用户刷新目录可选择新的探索快照；不能在旧 cursor 请求中默默升级。stream 的正文与本段人物/角色始终来自自己的 publication，不能换成后来的人物简介或头衔。

## 6. 只读 API

浏览器经过 Rust `/api/v1/public/*`，Python sidecar 使用对应 `/v0/*`。所有读取无模型、无新 canonical ID、无修复写入。新领域查询分属 reader_streams.py 与 reading_events.py；router / Rust 接线由一个后续任务完成。

| 浏览器路由 | 合同 |
| --- | --- |
| GET /api/v1/public/reading-streams?catalog=&limit=20&cursor= | 已发布 stream 目录；首次解析快照；排序 document_id/revision_no/stream_id，不混合多个 revision |
| GET /api/v1/public/reading-streams/{stream_id}?catalog= | stream 标题、章目录、unit/group 总数、manifest hash、起始 locator；不内联全部正文 |
| GET /api/v1/public/reading-streams/{stream_id}/units?catalog=&limit=20&cursor= | 双向有界正文页，prev_cursor/next_cursor、ordinal、group continuation、文本 segments、context 和 source anchors |
| GET /api/v1/public/reading-streams/{stream_id}/groups?catalog=&limit=50&cursor= | 按阅读顺序分页的轴区段，首尾 unit locator；不一次下载全世界时间线 |
| GET /api/v1/public/reading-streams/{stream_id}/locate?catalog=&unit_id= | 精确 unit 所在正文页/游标、相邻 group 页入口；不从首页翻到目标，不按字词/年份搜索猜落点 |
| GET /api/v1/public/reading-events/{event_id}/preview?catalog= | 快照内名称、各来源时间观察、来源名、可用的来源译文摘录及原文入口；无正文时只有已有事实字段，不临时生成摘要 |
| GET /api/v1/public/reading-events/{event_id}/targets?catalog=&limit=20&cursor= | 分页列出该 canonical Event 的精确正文位置、来源/章名、relation、短摘录；current 与 mention 明确分开 |

既有 `/api/v1/public/events/{id}`、`/entities/{id}`（内部仍对应 `/v0/events/{id}`、`/entities/{id}`）增加可选 catalog；不带时保留原行为，从阅读进入时必须携带。复用既有详情组装，source representations、相关对象及 Resolution/relations 均限定到该 catalog 实际成员，不另建平行详情服务。与该 snapshot 无明确绑定的 latest Reader Presentation 不覆盖固定详情，返回 null 并展示已有来源证据。详情的 cache key 同样包含 catalog。

Unit/context DTO 与 TypeScript 类型由协议任务统一提供。每页 limit 1..50，groups 可至 100；SELECT 使用稳定 keyset + limit+1，不读取全部正文后切片。正文页上限 2 MiB，提前停止并返回 next_cursor，不能截断某个 unit 的文字；单个 unit 连同其 metadata 上限 256 KiB，在发布编译时校验。反向游标绑定方向。preview 单次按需请求、最多 64 KiB（最多 8 个来源摘要，每个摘录至多 160 code points，并返回来源总数/更多入口）；只有摘录可明确省略，不能把它作为完整译文。targets 分页不能把首批当全部。所有 JSON 低于 Rust 现有 8 MiB 上限。

cursor 绑定版本、snapshot、stream、filters、方向和最后稳定排序键；未知/重复参数、错误 UUID、错范围 cursor 为 400。未知或未发布 stream/unit/event、早于 stream 发布的快照、不属于 publication 的 source anchor 为 404。source_missing/source_mismatch 沿用第一轮 409；读取内部不一致显式报错，不回填其他 revision。详情/预览缓存 key 包含 snapshot 和版本，不能只用 canonical ID。

原文仍调用第一轮 `/chapters/{publication_id}/sources/{anchor_id}` 的唯一 source reader，code point、原始 bytes SHA 与权限规则不变。Event Preview 的 excerpt 来自有 current 关系的已发布译文 block；只有回溯提及时须标明“提及”，不能伪装发生段落。

## 7. 定位选择与当前片段

“查看事件”打开既有 Event Detail 并保存 return token；“定位发生位置”只从 targets 中 relation=current 的位置选择。一处可直接跳转，多处展示来源/章节让用户选；没有 current 则明确暂无已收录发生段落，允许查看详情或标明为“提及”的材料。绝不把第一次字符串命中或最近年份当事件位置。“其他记载”始终明确显示来源切换。

当前人物/地点直接消费 active unit.context_entities；主要项优先、同类按本段出现顺序，按 canonical ID 去重但保留各条来源/事件角色；默认最多 6 位人物、4 个地点，其他可展开。政权和其他对象单列，不将军队/政权当人。未知/缺失关联显示无明确关联，不填整章人物或世界快照。失去当前段时清空而非留下上一段人物。

任何长期身份/关系都不从本轮 context 推导；第三轮可以引用 `{stream_id, publication_id, unit_id, narrative_time, current_event_refs}` 作为读取上下文，另行定义有效时间和状态依据。

## 8. 验收分层

自动验证覆盖 schema/ref/span/历法分组、不可变发布和恢复、snapshot SQL/游标、真实浏览器交互；真实内容验证检查主叙事与回溯、同名事件、主要人物、角色归属和原文支持。既有 #541 作为负例来源，不能自动宣称其旧数据已修复。

本轮首先交付有明确来源的连续阅读与导航，不以时间轴截图或通过 mock API 代替整链验收。界面、恢复、性能和验收场景见 [reading-experience.md](reading-experience.md)。
