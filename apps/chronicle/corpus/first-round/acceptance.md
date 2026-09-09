# C2 第一轮真实内容验收记录（T19）

任务：C2-R1-T19（Issue #569），依赖 C2-R1-T18（Issue #568）。
契约：`apps/chronicle/docs/chapter-production.md` §9、
`apps/chronicle/docs/review-workflow.md` §5、
操作入口 `apps/chronicle/docs/chapter-acceptance.md`。
逐案独立结论索引：`manual-content-review.json`（本目录，与本文同次提交）。

> 结论前置：**本次 live 内容验收未通过（NOT_PASSED）**。
> 真实 provider 调用、Studio 交互审核、浏览器阅读与独立人工逐章核对
> 均未执行（见 §4 阻塞项）。fixture 离线 PASS 仅证明编排与契约形状，
> **不能作为译文内容正确证据**，本文不以脚本 PASS 代替内容验收。

## 1. 冻结候选与来源

- candidate commit：`b611c33a50f30e895fd6aaeb9c8c4168be5d9bc1`
 （origin/main 在本记录编写时即该提交，T18 PR #613 已合入）。
- 工作区状态：本记录编写基于上述干净检出起草，`git_clean` 以证据生成时
  `first_round_gate.py` 输出为准；若 PR 推送后产生新提交，以 PR 终态
  commit 为准，不追认旧 SHA。
- 冻结语料包：`source-pack.json`（`pack_id=c2-r1-t02-first-round-v1`），
  两部著作、两个 revision 上传：
  - `ingest/sanguozhi-three-chapters.md`（三國志三章同一 revision），
    `sha256=a5dc345f7163cc01632e443cad93fbb85015b8dd277713e56c722ddfa5236076`；
  - `ingest/zizhi-tongjian-065.md`（通鑑卷65独立 revision），
    hash 见 `ingest-manifest.json`（`prepared_manifest_sha256=ff51bf140b1ce4aaa6ef8eb2184a2c2260481cf17257bfff048b62b5524db012`）。
- T02 核对点：`cases.json` 13 个真实核对点（T02-C01…C13）＋1 个合成负例
  （T02-N01，`synthetic=true`，禁作史料引用）。逐章独立结论状态见
  `manual-content-review.json`：本轮 13 个真实案例全部为 `pending`，
  无独立复核结论。

## 2. 实际运行过的检查（可复现）

以下均在本候选检出上实际运行，非历史引用：

- `python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_first_round_gate.py' -v`
  —— 12 tests OK（与 T18 记录一致的 fixture 端到端断言、live 七类拒绝、
  READY 零 provider 调用、无直写 DB、合成文本装配与故障闭环）。
- `python3 apps/chronicle/acceptance/first_round_gate.py --mode fixture --env-file /tmp/chronicle-first-round-test.env --source-pack apps/chronicle/corpus/first-round/source-pack.json --evidence-dir /tmp/chronicle-first-round-offline --allow-dirty`
  —— PASS：2 works（三國志 3 章＋通鑑 1 章，plan/切片绑定/接受/装配全经真实入口），
  10 故障注入全部 fail-closed，pair 初始 uncertain 且阻塞、batch 默认 uncertain。
  **该 PASS 明确标注 `fixture_only`，不是 live 内容证明。**
  （`--allow-dirty` 仅本地迭代使用；CI 运行严格干净检出。测试 env 文件内容见
  `chapter-acceptance.md` §1，不含秘密。）
- live 探针（非交互 stdin，如实拒绝）：
  `python3 apps/chronicle/acceptance/first_round_gate.py --mode live --env-file /tmp/chronicle-live-probe.env --source-pack apps/chronicle/corpus/first-round/source-pack.json --evidence-dir /tmp/chronicle-first-round-live-probe < /dev/null`
  —— FAIL（符合预期）：`live mode requires an interactive terminal: stdin is not a TTY,
  so no operator could resolve blocking reviews in Studio`。
  证明 live 入口在无人值守环境下 fail-closed，不会静默自动审核。
  （探针 env 仅为占位值：`CHRONICLE_MODEL_ENDPOINT=https://example.invalid/v1` 加
  非秘密哑值，无真实凭据。真实 live 运行的 canonical 命令见
  `chapter-acceptance.md` §2：`--env-file .env.chronicle` 须填入真实
  provider 配置，且必须在交互式终端执行。）
- `python3 tools/validator_ready.py --root docs/tasks/chronicle/first-round --check --format json`
  —— 仍报 `task C2-R1 has no status`（T16 已记录的根级问题，修复超出本任务文件所有权，未改）。
- 本目录新增 JSON 已做解析与引用存在性检查（见 T19 台账 Verification），
  不含任何秘密（仅 commit/SHA/文件位置/状态）。

## 3. 真实模型预检（未执行）

固定完整章的实际 context/output 能力、终止状态、耗时和用量：
**未测量**。无 provider endpoint、无模型身份、无用量数字，
本文不填写任何预算满足结论，不宣称未经测量的正确率。
容量上限仍以 `chapter-production.md` §3 为准（32768 规范化字符/章等），
四章名义字符数见语料 README（12572 / 5018 / 3583 / 10680），
实际请求/返回用量待真实运行时记录。

## 4. 真实闭环（未执行，阻塞项如实记录）

| 步骤 | 状态 | 说明 |
| --- | --- | --- |
| 全新空环境＋live 配置（fixture 禁用） | 未执行 | 无可用真实 provider 凭据与空 Compose 目标栈；不复用旧 C1 T17 或调试库 |
| 真实 Studio 导入两 revision、多章与第二来源 | 未执行 | 同上 |
| pair/batch 审核（操作人员按原文决定，记录 default/例外/uncertain） | 未执行 | 需要交互式 Studio 操作员；脚本不填身份答案，本次亦未填 |
| 生产重启/接管、发布与公开阅读 | 未执行 | 同上 |
| 两 revision 来源固定、连续审核/返回路径 | 未执行 | 同上 |
| job/publication/source hashes 及浏览器观察归档 | 未执行 | 无产物可归档，不伪造 hash |
| 逐章全文＋嵌注独立核对（首尾/段落、指代、别名、人/地/政权、事件角色/时间、引用支持） | 未执行 | 需人工或独立较强复核者；开发模型不自证内容正确，本次 13 案全部保持 `pending` |
| #541 回归发现 | 未涉及 | 若后续真实核对涉及其案例，届时记录结论；不自动关闭该旧 tracker |

## 5. 内容 verdict

- 已知关键内容错误：**未知**（未做独立核对，不能宣称“无已知错误”）。
- 13 个真实定位案例独立结论：**0/13**（全部 pending，不伪造结论）。
- 模型输出预算满足性：**未测量**。
- 闭环可追溯证据：**无**（fixture manifest 仅为编排证据，已存 `/tmp` 临时目录，不作为交付物）。
- 本记录 verdict：**NOT_PASSED**。后续拥有者用新 candidate 重跑受影响门时，
  以本记录 §4 为待办清单，以 `manual-content-review.json` 为逐案登记簿。

## 6. 后续 live 运行待办（给执行者）

1. 按 `chapter-acceptance.md` §2 准备全新环境与 live 配置（fixture 相关变量不得设置，
   endpoint 不得内嵌凭据），先拿到 `result=READY` manifest（`provider_calls_by_t18=0`）。
2. 在 READY 基础上执行真实上传→后台处理→交互审核→发布→浏览器阅读与原文核对，
   记录实际模型、prompt/schema/plan/limits 版本、终止状态、运输/语义修正次数、用量和耗时。
3. 由人工或独立较强复核者逐章核对全文和嵌注，逐条填写 T02 cases 并登记到
   `manual-content-review.json`（`pending`→`pass`/`fail`，附 reviewer 与证据定位）；
   任何关键漏译/误指代/无据补写/错误合并/无法核对均判不通过，保留原脚本结果和独立内容失败记录。
4. 修复回相应拥有层，用新 candidate 重新跑受影响门；只有实际验收通过后，
   再按 task-completion 流程完成 T19 及本轮索引默认分支对账，同步 #548 验收和关闭。
   #549/#550 保持未启动。

## 7. 真实验证轮次 ffc58aa（进行中，verdict 仍为 NOT_PASSED）

- 候选：`ffc58aa`（分支 `agent/executor/7dfa2567b43d`），镜像 `loom-chronicle:t19-ffc58aa`，
  模型 `gpt-5.6-luna`，prompt v1→v2→v3 均经真实调用验证。
- 服务器证据目录（测试机本地，不进仓库）：`/srv/loom-t19-evidence/ffc58aa/`
  （manifest、两 job 终态快照、worker `chapter_failed` 真实错误行）。
- 旧失败 job `75f34121`（三國志 revision）原样保留：3 次 extract 失败后
  `needs_review`；新 job `db2980b9`（同一 revision）已跑 2 次 extract，均 fail-closed。
- 5 次真实 extract runs（先主传 chunk 0，每次初次＋1 次整章修正）：
  - v1：29→4（anchors×2＋time×2）。
  - v2：bundle-only→22（含 claim literal 5 误报，已定位为 T01 schema/检查自矛盾，见下）。
  - v2 retry：4→1（修正轮空 bundle 退化）。
  - v3 新 job：9→2（anchors×2）；v3 retry：bundle-only→9。
- 由此落地的拥有层修复（ dochter wire 无关，全部有 focused tests）：
  1. 修正轮 diagnostics 保留记录 temp id（此前 `ent_*` 掩码使不同记录坍缩去重，
     模型无法定位；`chapter_prompt.py`，prompt v2）。
  2. VERBATIM GROUNDING PROCEDURE：quote 逐字复制、block 范围核对、
     `time.original_text` 不得写入继承年月（此前模型屡次前补“二年/三年”；v2）。
  3. claim object 形状指引 `{kind,ref}|{kind:literal,value}`（v3）。
  4. T01 自矛盾对齐：candidate schema＋API text_format＋C0 LITERAL 均为
     `{kind:literal,value}`，唯 python references 检查要求 `ref`，致任何 literal
     都无法同时通过两门；已按 schema 一侧对齐（`chapter_contract.py`），
     未放宽任何 grounding 要求。真实 attempt-2 候选复跑验证：22→17 错误，
     5 个 claim 误报消除，无新增错误。
  5. `chapter_failed` 日志携带真实错误（此前恒为 None；`chapter_stage.py`，
     生产日志已验证）。
  6. `CHRONICLE_MODEL_TIMEOUT_SECONDS` 进入 joint chapter provider
     （此前恒为 600s 默认；`model_provider.py`＋`chapter_stage.py`）。
  7. 每次模型调用记录 `latency_ms`（`chapter_extraction.py`）。
- 实测用量（先主传 chunk 0，gpt-5.6-luna）：prompt 约 39k→78k chars（含修正轮），
  单次调用耗时约 147s→422s，无 transport error（transport 内部重试在成功路径
  不可见，属已知证据缺口，未虚构数字）。
- 顽固剩余错误类（verbatim 程序已覆盖仍偶发，属模型采样方差）：
  真实 quote 配错 block（如“曹公征徐州”在 b_011 却标 b_009）、虚构 quote
  （如“先主留張飛守下邳”全章 0 命中，多次复现）——validator 均正确 fail-closed。
- 本轮结论：NOT_PASSED。13 案仍全部 `pending`；第二书（通鑑）尚未开始；
  Studio 人工 review、发布、Reader 阅读、13 案独立核对均未执行。

## 8. 真实验证轮次 0410b15d → 26eb34c1 → 9902a374 → 23da90b1（进行中，verdict 仍为 NOT_PASSED）

- 候选链（分支 `agent/executor/7dfa2567b43d`，每次修复均有 focused tests，契约只收紧不放宽）：
  - `0410b15`：rebase 到 origin/main（`#615` GitHub-Issue 支持＋本分支
    `Multica-No-Close` opt-out 合并），PR #614 恢复 MERGEABLE。旧失败保留，
    新 project `chronicle-t19-0410b15d`（端口 8081）＋新证据目录重跑。
  - `26eb34c`：相等诊断携带双方值（`surface 'X' must equal selection.quote 'Y'`；
    `chapter_contract.py`＋4 个新单测）。此前 value-free 诊断使整轮修正作废。
  - `9902a37`（prompt v4）：`resolution:{status}` 未钉值致模型编造 `'new'`，
    校验放行、assemble 才炸；在 prompt 钉死 `"unresolved"` 并在校验层前置
    同规则失败（entities only，与 assembler 一致），prompt v3→v4。
  - `23da90b`（prompt v5）：VERBATIM 加 `(d)` 繁简不转换（通鑑 run 曾出简体
    surface/quote；v5 起 runs 已全为繁体）。
  - `558c4bd`（prompt v6，已 push 未 live）：surface 定义为 occurrence 原文拷贝
    （`曹公征徐州` 取 surface `曹公征徐州` 非 `曹公`；`備` 取 `備` 非 `劉備`）。
- 服务器证据目录（测试机本地，不进仓库）：`/srv/loom-t19-evidence/<SHORT>/`
  （preflight manifest、job 终态快照、operator decision 记录）。
- 关键真实结果（模型 `gpt-5.6-luna`，来源 SHA 与冻结包一致 `a5dc345f`/`b9831c28`）：
  - 26eb34c1 三國志 chunk 0/1：初次 5 errors → 修正 0 errors，一次通过；
    chunk 2 后 job 倒在 assemble（`ent_001 resolution status 'new'`），驱动 v4 修复。
  - 9902a374 通鑑卷65（10715 字整章）：run 1 初次空 bundle、修正 17 errors
    （简体 surface 等，诊断已携带双方值）→ Studio bounded retry → run 2 通过；
    全 8 阶段 completed 并 publish，publication `01a086d0`，Reader 目录可查、
    全文 14362 字（首建安十一年正月，尾新都郡賀齊太守），artifact/bundle/catalog
    SHA 已归档。这是本轮第一个完整闭环证据（单章）。
  - 9902a374 三國志 chunk 0：3 次 bounded attempts＋1 次 supervised resume
    （chunk_failure review `f210a2cf` operator resolve＋resume，返回路径真实证据）
    仍未通过（10→1→10 errors，采样方差＋顽固 anchor），第二 review 保持 open
    作 terminal 证据，job 保留 needs_review。
  - 23da90b1 三國志 chunk 0：run 1 transport 空回包（provider 侧，非语义）；
    run 2 收敛到 3 errors；run 3 surface 类消失、剩 4 anchor miss；
    已做第二次 supervised resume（review `dc360d41` resolve＋resume），进行中。
- 仍 NOT_PASSED：三國志三章未完成 assemble/resolve/publish；跨章 pair review、
  第二来源 batch、重启/接管、13 案独立结论（仍全部 `pending`）、四章 Reader
  浏览器验证均未完成。

## 9. 真实验证轮次 855a1dc0（prompt v6＋anchor-hint，进行中，verdict 仍为 NOT_PASSED）

- 候选：`855a1dc`（prompt v6：surface 定义为 occurrence 原文拷贝并举例；
  validator：anchor 零命中诊断区分“配错块”（给全章计数＋首个所在块，
  如 `ent_0002 b_009→b_011` 即首轮“曹公征徐州”旧案）与“全章虚构”（明确要求换引文），
  契约不变）。新 project（端口 8085）＋新证据目录＋新数据目录；旧失败全保留。
- 三國志 job 1（`443136b6`）：chunk 0 run 2 初次空 bundle、修正 0 errors 通过；
  三块全过 assemble；resolve 开出 7 个同 revision 跨章 entity pair review，
  operator 已按原文逐条裁决（5 default `same_entity`＋2 简繁例外 `same_entity`，
  决定与 rationale 存 `operator-pair-decisions.json`），7/7 resolved 后 resume，
  resolve completed；但 publish fail-closed：`publication_plan_stale`
  （冻结基线 null vs 通鑑先发布形成的 catalog v1）。经查设计如此
  （`resolve_publish.py`＋`chapter_stage.py`：冻结计划永不 rebase），非 bug；
  job 1 作 terminal 证据保留，已开同 revision 新 job 重走 resolve（基线 v1）。
- 通鑑 job（`c1c487cb`）：attempt 2 通过并完成 8 阶段，publication `01a08753`
 （catalog `fe0bd3de` 即 v1），Reader API 全文 14984 字 64 块、首尾完整；
  真实 chromium headless 渲染 DOM 17413 字、首尾标题齐全，截图已归档
  （`reader-zztj.png`）。这是第二书完整闭环。
- 生产重启/接管真实证据：SG job 2 运行中 `docker restart` worker；
  日志 `signal 15; finishing current step...` 后新实例
  `claiming ... (lease 300s)` 接管，job 继续运行（`worker-restart-takeover.log`）。
  代价：一次 claim 消耗被计入 job 3/3 bounded budget（见下）。
- 三國志 job 2（`d3eba4a3`）：chunks 0/1 通过、chunk 2 差 4 anchor/alias miss；
  job claims 用尽（重启一次＋重试两次）后 Studio retry 按设计拒绝
  （`exhausted its bounded retries (attempt 3 >= max_attempts 3)`），
  不放宽 bound；job 2 作 terminal 证据保留，已开 job 3（`24fe7e6c`，同一定 revision）。
- 本轮结论：NOT_PASSED。待 job 3 三块→新 pair review 重裁→publish（基线 v1）→
  三章 Reader（含真实浏览器）→13 案独立结论→台账对账。

## 10. 发布排序与 staged label 冲突（真实观察，verdict 仍为 NOT_PASSED）

- SG job 1 publish-stale 后开 job 2（同 revision `d594c4b6`）：chunks 0/1 通过、
  chunk 2 差 4 miss；claims 用尽（含重启验证消耗的一次）后 retry 按设计拒绝
  （`attempt 3 >= max_attempts 3`，不放宽）。job 2 作 terminal 证据保留。
- SG job 3（同 revision）：三块全部提取＋装配通过，但 resolve fail-closed：
  `bundle label 'c1rev-d594c4b69c74' already exists with different content`
  （库中 job 1 的 bundle `9110...` vs job 3 的 `05ec...`）。根因：
  staged store 按 revision label first-writer-wins（`staged_store.py`），
  同 revision 第二个模型产物永不能 resolve；同字节重传回 `duplicate=True`
  同一 revision（无新 label）。未删改 staged 行、未放宽 bound、未重设计
  label 语义（属持久层架构决策，超出本任务范围，已如实上报 reviewer 定夺）。
- 恢复路径（operator 决定，有记录）：新的三國志 document＋revision
  （`7c324401`，同冻结字节，SHA `a5dc345f` 重新验证，`duplicate=False`）
  ＋ job 4（`e76081d3`），作为独立导入事件记录；jobs 1–3 全部保留为
  terminal 证据。job 4 的 resolve 将以 catalog v1（含已发布通鑑）为基线，
  预期出现跨书 batch 候选（第二来源覆盖）。
- 本轮结论：NOT_PASSED。待 job 4 三块→pair（＋可能 batch）review 裁决→
  publish→三章 Reader（含真实浏览器）→13 案独立结论→台账对账。

## 11. Job 4/5 与 claim-budget 边界（真实观察，verdict 仍为 NOT_PASSED）

- Job 4（`e76081d3`，revision `7c324401`）：chunk 0 经 5 次人工门控运行通过
  （run1 transport 空回包；run2 surface `曹公/曹公征徐州`；run3 顽固 anchor；
  run4 全员 hedge 违规；run5 通过），chunk 1 通过，chunk 2 差标点 `。`
  evidence miss＋anchor hints（均可修复类）；但 job claims 到 5/3，
  Studio retry 按设计拒绝、resume 要求 needs_review（job 为 failed）——
  chunk 级仍有 retries 也无 operator 恢复路径。job 4 作 terminal 证据保留。
- Claim-budget 教训（上报 round owner，不自行放宽）：bounded job claims（3）
  在逐块模型方差下烧完，而 chunk 级 retries 仍在；`failed`＋claims 用尽是死局，
  只有 `needs_review` 才有 supervised resume 出路。失败界本身工作正常。
- Revision `7c324401` 的 label 空闲（job 4 未到 resolve，无 staging），
  job 5（`0634b3c8`，同 revision）resolve 路径干净，已排队。jobs 1–4 全保留。
- 本轮结论：NOT_PASSED。待 job 5 三块→review 裁决→publish→三章 Reader
  （含真实浏览器）→13 案独立结论→台账对账。

## 12. T02 十三案 operator 草稿结论（人工逐条核对，非最终 PASS）

> 方法：executor 人工对照原文与真实模型产物逐条核对（非模型自证）。
> 通鑑依据已发布产物（publication `01a08753`，artifact `b1aaf568`）；
> 三國志依据 job 1 accepted-but-unpublished artifacts（三块 47/48/38KB，
> 翻译与 bundle 均已落盘 `sg-job1-chunk*-translation.txt`）。
> `manual-content-review.json` 保持全部 `pending`，以下为草稿结论，
> 须独立 reviewer 确认后方可转正；总体 verdict 仍为 NOT_PASSED。

| 案 | 译文侧 | bundle 侧 | 草稿 |
| --- | --- | --- | --- |
| C01 先主/備 | 開篇先主姓刘名备；先主124×一贯 | SG1 備→ent_005；SG0 两 mention unresolved；ch0↔ch1↔ch2 pair 均 same_entity | PASS（记 SG0 内链缺口） |
| C02 周瑜/公瑾 | 公瑾15×（与 T02 计数一致）＋卷末孤念公瑾 | aliases 公瑾/周郎 grounded | PASS |
| C03 魯肅/子敬 | 子敬3×＋持鞍下馬全段 | aliases 子敬/肅；pair same_entity | PASS |
| C04 赤壁跨章 | 兩章均有遇赤壁＋疾疫＋並力迎擊 | SG1 赤壁 place；ZZ evt_004 赤壁之戰；事件跨章未裁决 | PASS（记事件未裁决） |
| C05 赤壁跨書 | SG1 遇赤壁＋ZZ 進遇赤壁＋疾疫互證 | 跨書 batch 从未开出（ZZ 单发，SG 未发布） | PASS（记跨書未裁决） |
| C06 周瑜督軍跨書 | 兩書任命均渲染（左右督→左右都督/並力→合力用词漂移，记观察） | 人名职事对象一致；跨書未裁决 | PASS（记用词漂移＋未裁决） |
| C07 南郡/江陵 | 追至南郡／守卫江陵分明 | 无南郡 entity、无合并（uncertain 平凡成立）；南郡未建模记 recall 观察 | PASS（记 recall 观察） |
| C08 典略注 | 3×《典略》说/又记载，位置正确 | 注无伪造归属 | PASS |
| C09 江表傳注 | 7×《江表传》说，位置正确 | 同上 | PASS |
| C10 馬超背景 | 周瑜演说内背景铺陈完整 | 无馬超 entity/event/claim | PASS |
| C11 首部完整 | 四章開篇俱全 | — | PASS |
| C12 尾部完整 | 先主傳惠陵＋神仙傳注；通鑑賀齊太守（与原文末一致） | — | PASS |
| C13 習鑿齒論曰 | “习凿齿评论说”＋位置正确（劉備遗言后、王威前） | 无習鑿齒 entity（未误作同期言论） | PASS |

关键负发现（阻止转正，必须先解决或由 owner 定夺）：

1. **SG chunk 0 骨架 bundle**：12591 字先主傳只产出 1 entity（刘备）＋1 event
   （永安宮去世）＋1 claim＋2 unresolved mentions，而译文含曹操37×/孫權19×/
   諸葛亮17×/关羽14×。validator 只量结构（禁空 bundle），不量召回；
   修正轮“修好唯一报错”激励最小修复。这是 T19 “身份关联、来源核对可用”
   对先主傳不成立的直接证据。修召回下限属契约语义决策，未擅改，上报定夺。
2. **ch0 canonical 简体**：先主傳 entity 名用简体「刘备」（通鑑章 15 entities
   全繁体）。身份无误，内容质量观察项。
3. **SG 未发布**：以上 SG 结论基于 accepted-but-unpublished artifacts；
   四章 Reader、发布闭环、13 案转正均待 SG  Booker 发布后由独立 reviewer 定夺。
