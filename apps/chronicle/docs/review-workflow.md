# Chronicle 第一轮：合并审核契约

状态：**本轮实现契约，尚未实现**。章节及引用依赖 [chapter-production.md](chapter-production.md)；此文拥有队列、来源查看和交互规则。旧实现基线见 [review-publication.md](review-publication.md)，新功能由 [第一轮任务图](../../../docs/tasks/chronicle/first-round/README.md) 交付。

第三轮在同一审核外壳中增加阶段依据包，扩展合同归 [person-state-reading.md §5](person-state-reading.md#5-阶段依据审核)。该扩展新增 review_scope、按 scope 分派的评估表单和候选来源读取；原身份决定、连续操作与来源权限保持此文规则，由第三轮单独交付。

## 1. 决定的含义

保留既有 allowed decisions、rationale、confidence、batch 默认和逐组例外；继续让应用层在同一事务中检查 graph、记录 decision 和终态。来源展示、翻译和名称不产生身份等价。

新增的 chapter_pair 只是两个未发布章节表示之间的普通候选问题。没有 published canonical 时不得借用 batch 标识伪造一个。按 (bundle,ref) 显示两侧的实际章节和出现记录。published↔incoming 的 batch 继续逐组保留材料；显示所有组和全部成员的入口。

“暂时跳过”仅改变当前浏览会话，不写 ReviewItem、不调用 dismissed，也不提交 uncertain；仍待审并阻塞 job resume。“提交不确定”才是持久化的明确决定。恢复导入仍由现有 resume API 检查该 job 全部种类的 open reviews。

## 2. 队列 API

沿用 GET /api/v1/studio/jobs/reviews，以新分页替代前端固定首 200 项。过滤字段固定：

- status=open|resolved|dismissed|all，默认 open；
- job_id 可选 UUID，省略表示所有任务；
- link_kind=entity|event 可选；
- limit=1..100，默认 50；
- cursor 可选，不与 offset 混用。

返回 chronicle.studio-review-page / 0.2：query、items、next_cursor、open_count、observed_at。items 保留既有可读摘要和 review_id/status，并提供不可变 plan_fingerprint。open_count 是当前 job/link_kind 范围全部待审数量，独立于当前页及 status filter；属于本次读事务观察，不是固定“第 N/M 项”的分母。

排序只使用 (created_at,review_id)，不按会改变的 status 排序。cursor 是版本化不透明编码，绑定规范化 filters 及最后排序键；无效编码、参数重复或换 scope 使用旧 cursor 返回 400。服务端 limit+1 确定下一页。

队列 API 任务同时更新 typed client 和现存验收脚本消费者。新增 listReviewPage 返回完整分页结构；现有 listReviews 暂通过同一新 API 遍历全部分页，保持尚未接线页面可运行，不保留另一套旧服务端分页。连续审核 UI 任务改用逐页读取后移除这层过渡 wrapper。

## 3. 连续审核状态机

URL 保存 status/job_id/link_kind/current review；sessionStorage 保存本 tab 的列表 cursor、scroll/anchor，以及独立的 open 遍历 cursor/已跳过集合。all/resolved 列表的返回状态不能作为 status=open 的连审 cursor。草稿以 (review_id,plan_fingerprint) 为 key，含 decision/rationale/confidence、例外开关和全部 group overrides；fingerprint 定义在章节契约 §6，排除 mutable decision/status。版本不匹配时标明失效，不套入新计划。

- 固定可触达操作区提供“保存并下一项”“暂时跳过”“返回队列”。长章页底部无需滚回顶部；移动端不遮住最后一行／输入框。
- 提交期间防重复点击；只在收到成功并核对提交的 review_id 后清掉该项草稿、寻找下一项。任何 400/409/503、断网、未知提交结果都保留草稿。
- 网络结果未知时 GET 当前项，展示服务器决定；不自动重发覆盖，不将失败当成功。409 canonical_identity_conflict 保留可读冲突和所有例外草稿。
- 切换 review 时从该 review 的隔离草稿初始化；Entity→Event、A 的 group→B 的 group 均不得带入上一项值。迟到响应也按其原 review_id 处理。
- 下一项来自当前 scope 的 open 队列，并再次核对状态；另一 tab 已处理者不再提交。暂时跳过项在本轮导航中避开，重新开始本轮可恢复。
- 页尾从队首重新扫描一次，找出仍 open 且未跳过的记录，包括在旧 cursor 之前晚提交的新行。遍历有 page/count 进度，不无界递归。
- 再扫描后：有仅跳过项 → 显示“本轮已查看，仍有 N 项暂时跳过”，N 只数当前仍 open 的 skipped IDs，不取本地集合大小；服务端 open_count=0 → 显示“当前范围暂无待审项”；并发范围持续变动 → 显示刷新入口和观察时间。不得宣称整个导入完成。
- 返回队列、刷新、浏览器前进后退恢复相同 scope 与位置。改变 scope 清分页状态，但不会把其他项的草稿套到当前项。持久化决定只以服务端为准。

## 4. 审核来源 DTO 与查询

detail 中增加轻量 SourceContext descriptors，不内联每个成员的完整章。每个 descriptor 有：context_id、(bundle,bundle_sha256,record_ref)、job/revision/chapter、artifact_sha256、source_title/chapter_title、available 状态、anchors 摘要和 evidence_kind。

evidence_kind 区分 direct_claim、mention、record_source、event_context、translation。参与事件的 Claim 可以作为 event_context，不能伪装成该人物的 direct_claim。没有直接 Claim 或 mention 的对象仍可经 mandatory record_sources 查看原文，类型为 record_source。辅助译文单独标示“白话译文”。

GET /api/v1/studio/jobs/reviews/{review_id}/contexts?group_id=…&limit=50&cursor=…
按冻结成员列表返回全部来源 descriptor；chapter_pair 可省略 group_id。limit 1..100，cursor 绑定 review/plan/group。每组都可加载所有成员，不能只展示左右各第一个。detail 保留总数和上下文入口，不能以分页的首批冒充完整组。

GET /api/v1/studio/jobs/reviews/{review_id}/sources/{anchor_id}?view=window|chapter&cursor=…
复用章节契约中的 source reader，返回版本化原文、窗口或整章分页。必须验证 anchor 属于该 review 的 frozen member，bundle/hash/record 和 accepted artifact 精确匹配；既有 chapter_pair 与 batch 两侧都支持。不可按名称找来源，不可从最新 revision 取材料，不可全文搜索命中即认定该位置。

源文件 hash/范围不符 → 409 source_mismatch；文件缺失 → 409 source_unavailable；不属于该 review 的 anchor → 404；参数错误 400。未知或未配置 revision 的旧局部 fixture 可明确 unavailable 并保留原有直接 Claim，不为旧产物补造定位或迁移生产数据。

Studio auth 继续由 Rust front 在路由/资源检查前执行：匿名或错误凭据 401，未配置管理员 503。所有原文查询只读。不把私有 documents/content 直接开放给公众；public 入口还须额外验证 publication 可见范围。

服务端在一次详情请求内按 (bundle_sha256,record_ref) 去重加载，来源文件按 revision/hash 缓存到本次请求。原文窗口前后各 400 字、整章每页最多 16,000 字，使用章节契约中的 code point 坐标和服务端高亮片段。分页数据的完整性由 has_more/next_cursor 明示。

## 5. 展示与故障

比较页先显示对象/事件、来源、章节、实际出现材料和关键差异；内部 temp IDs、hashes、candidate keys 收入审计详情。相同名称但不同章的材料仍分开可读。

引用依次展开“原文片段 → 前后文 → 整章”；不改变当前决定草稿，不跳回页首。请求 key 包含 review/plan/context/artifact，关闭、换项、改变组时迟到响应不能覆盖当前材料。正文和译文均作为文本渲染，引用失败保留表单和已读材料，可重试。

验收必须操作实际页面：450 项以上、多 job、相同 created_at、前页处理后继续、队尾、两 tab 争用、晚提交、逐组例外、失败后刷新、只剩跳过项；以及无直接 Claim、重复引文、BOM/CRLF/扩展汉字、两个版本文字相同但来源不同。源码包含按钮文字或 fetch mock 通过不足以证明连审交互。
