# C2 第一轮真实内容验收记录（T19）

任务：C2-R1-T19（Issue #569），依赖 C2-R1-T18（Issue #568）。
契约：`apps/chronicle/docs/chapter-production.md` §9、
`apps/chronicle/docs/review-workflow.md` §5、
操作入口 `apps/chronicle/docs/chapter-acceptance.md`。
逐案独立结论索引：`manual-content-review.json`（本目录，与本文同次提交）。

> 结论前置：**本次 live 内容验收未通过（NOT_PASSED）**。
> 真实 provider 调用、Studio 交互审核（含 7 pair same_entity 裁决）、
> 真实浏览器阅读（通鑑章）均已执行；SG 书发布、四章 Reader、
> 13 案独立结论仍未完成（见 §0 当前候选摘要与 §11 待办）。
> fixture 离线 PASS 仅证明编排与契约形状，
> **不能作为译文内容正确证据**，本文不以脚本 PASS 代替内容验收。

## 0. 当前候选权威摘要（current-candidate，唯一可审计口径）

- 代码候选：`0bb5c6a07226d4f877b63cd5a6ff9757f3a441ec`
  （prompt v8：v7 resolve-hedging 澄清＋temp_id 001–999 钉值；
  validation report v0.2 recall 观察节；分支
  `agent/executor/7dfa2567b43d`，其后若有提交均为纯文档记录）。
- 模型：`gpt-5.6-luna`（三路）；镜像 `loom-chronicle:t19-0bb5c6a0`
  （SHA 校验一致）；测试服务端口 8088，新 project/数据/证据目录
  （`/srv/loom-t19-evidence/0bb5c6a0/`）。
- 来源：`a5dc345f`（三國志三章）/`b9831c28`（通鑑卷65），与冻结包一致。
- 当前状态：三國志三章已发布（publication `01a08997`）＋通鑑已发布
  （`01a08975`）；27 review（22 同书＋5 跨書）全部浏览器内真实
  decision-click（34 截图＋终局快照）；章内 mention 链接已建模验证
  （见 §18）；但 v8 轮暴露译文空心/ condensed 缺口（见 §18），
  13 案独立结论 **0/13**，verdict **NOT_PASSED**。
  细节见 §12、§16–§18；§1–§6 为历史基线，§7–§15 为中间轮次，
  不得作为当前验收证据引用。

## 1. 冻结候选与来源（历史基线：candidate `b611c33`，仅记录起点）

> 本节（§1–§6）为 T19 启动时的诚实 NOT_PASSED 基线记录
> （candidate `b611c33a50f30e895fd6aaeb9c8c4168be5d9bc1`），
> 其 “均未执行” 状态已被后续轮次（§7 起）取代。
> 当前可审计口径以 §0 为准；本节仅保留作历史对照，不得引用为现状。

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

## 12. T02 十三案 operator observations（观察记录，未计入独立结论）

> 方法：executor 人工对照原文与真实模型产物逐条记录所见（非模型自证，
> 非独立结论）。当前轮（v8, `0bb5c6a`）：三國志依据已发布产物
> （publication `01a08997`：先主傳 43 块 16516 字、周瑜傳 16 块 3182 字、
> 魯肅傳 10 块 5155 字）；通鑑依据已发布产物（publication `01a08975`，
> 62 块 2808 字）。四章 Reader API＋真浏览器首尾验证通过，
> 截图、DOM 断言与 canonical smoke 已归档。
> 历史注：5024 轮产物（`01a088b2`/`01a088e7`）与 job 1
> accepted-but-unpublished artifacts（先主傳 5139 字/骨架 bundle）
> 已由当前产物取代，仅作负证据保留（见 §13 与 §10–§11、§18）。
> **独立结论口径：0/13** —— `manual-content-review.json` 保持全部
> `pending`；下表每行均为 operator observation（not counted），
> 含 recall/空心缺口原样保留；任何“通过”含义的解读均属误读，
> 总体 verdict 仍为 NOT_PASSED。
> 审核对账注（单一口径，历史/当前已区分）：
> 当前轮（`0bb5c6a0/`）：`job-sanguozhi-FINAL.json`（job `14bb2587`
> completed，27/27 resolved，22 同书＋5 跨書，全部浏览器内真实点击，
> 34 before/after 截图）＋`reviews-FINAL/`（27 个终局详情）＋
> ZZ `job-zztj-FINAL.json`（job `24666b4f` completed，publication
> `01a08975`）。历史轮：`5024be17/`（22＋1，见 reconciliation）与
> `855a1dc0/`（7 review，publish-stale 终局），仅对照。
> `reviews-sg-open.json` 类文件均为裁决前历史快照，以 `-FINAL` 与
> decisions 文件为准；可重跑命令见各目录 `review-snapshot-reconciliation.md`。

| 案 | 译文侧所见 | bundle 侧所见 | 观察（含缺口） |
| --- | --- | --- | --- |
| C01 先主/備 | 開篇先主姓刘名备；先主一贯（v8 先主傳译文） | v8 先主傳 12 mentions resolved 12/12，m_001 先主→ent_001 劉備（跨度拷贝）；劉備三角：v8 轮 3 组（5a47c1af/836826b2/cdbbb0d0）＋历史（5024 3 组、855a1dc0 3 组）均 same_entity | 观察记录：章内共指在 v8 bundle 已建模；待独立确认 |
| C02 周瑜/公瑾 | v8 周瑜傳公瑾仅 2×（归一为周瑜；5024 轮 15×），卷末顾念周瑜（孤念公瑾转述） | 周瑜三角已裁决；alias 公瑾原文有据但译文归一，fidelity 观察 | 观察记录：身份无误，称谓保真观察保留 |
| C03 魯肅/子敬 | v8 子敬3×＋持鞍下馬全段俱全 | v8 27 组未涌现魯肅对（extraction recall 方差）；历史轮 pair（5024/855a1dc0）均 same_entity | 观察记录：v8 翻译俱全；本轮对缺失，缺口保留 |
| C04 赤壁跨章 | 兩章均有遇赤壁＋疾疫＋並力迎擊（v8 周瑜傳 condensed 但核心俱全） | v8 event 对 d7397a4b（赤壁之戰↔赤壁之戰）same_occurrence，浏览器裁决，随 `01a08997` 发布；历史 ZZ2 2 组 event 已裁决未发布 | 观察记录：v8 事件链接已裁决＋已发布；ZZ2 未发布终局保留 |
| C05 赤壁跨書 | SG 遇赤壁＋ZZ 進遇赤壁＋疾疫互證（v8 ZZ condensed 但核心俱全） | v8 跨書 5 组之二：赤壁地点＋赤壁事件 same_occurrence，浏览器裁决，随 `01a08997` 发布；历史：曹操 batch 已发布（ZZ v1）、ZZ2 12 组已裁决未发布 | 观察记录：v8 跨書事件/地点已发布；ZZ2 未发布保留 |
| C06 周瑜督軍跨書 | 兩書任命均渲染（v8 周瑜傳左右督任命缺失，记缺口；5024 轮有渲染但用词漂移） | v8 27 组与 ZZ2 12 组均未涌现督軍任命 batch；任命跨書 linkage 从未开出 | 观察记录：v8 周瑜傳任命缺失＋跨書未开出，缺口保留 |
| C07 南郡/江陵 | 追至南郡／守卫江陵分明（v8 ZZ 亦分明） | v8 南郡 entity 对 ca89410b 已裁决 same_entity（浏览器）＋已发布；南郡≠江陵从未合并 | 观察记录：南郡自身同一已发布；两者区分保持 |
| C08 典略注 | 3×《典略》说/又记载，位置正确 | 注无伪造归属 | 观察记录 |
| C09 江表傳注 | 7×《江表传》说，位置正确 | 同上 | 观察记录 |
| C10 馬超背景 | v8 ZZ 周瑜演说背景句俱全（馬超 x1） | v8 ZZ bundle（4 entities）無馬超 entity/event/claim | 观察记录 |
| C11 首部完整 | SG 三章開篇俱全；v8 ZZ 缺卷题行（卷第六十五/第065卷未渲染， fidelity 观察） | — | 观察记录：ZZ 卷题缺失保留 |
| C12 尾部完整 | 先主傳惠陵＋神仙傳注；通鑑賀齊太守（与原文末一致） | — | 观察记录 |
| C13 習鑿齒論曰 | v8 ZZ “习凿齿评论说”＋位置正确（x2） | v8 ZZ bundle 無習鑿齒 entity（未误作同期言论） | 观察记录 |

关键负发现（阻止转正，必须先解决或由 owner 定夺，见 §13/§16–§18）：

1. **空心/condensed 译文（当前内容失败，终局保留，不重写已发布产物）**：
   v7 先主傳出版物 43 块仅 2412 字（ratio 0.192，孫權/白帝 x0）；
   v8 通鑑出版物 62 块仅 2808 字（ratio 0.26，关键项各 x1，缺卷题行）；
   v8 周瑜傳 3182 字（ratio 0.63，缺左右督任命/陳就/蘇飛段，
   公瑾归一为周瑜）；v8 先主傳 16516 字（1.31）与魯肅傳 5155 字
   （1.43）完整。历史骨架 bundle（job 1 先主傳 1 entity＋2 unresolved
   mentions）已由 v7/v8 富 bundle 取代意义（12/12、19/19、8/10
   resolved），仅作历史负证据保留。recall 观察节使空心可见，
   但 validator 本身无 fidelity 门（§13 哲学不变）。
2. **用词漂移观察**：左右督→左右都督、並力→合力、`進` 主语弱化、
   孤念公瑾→顾念周瑜等，已记录在 C02/C05/C06 行，待独立 reviewer
   定夺是否关键。
3. **跨書矩阵（当前口径，见 §16 定义与 §18）**：
   已发布：v8 轮 5 组（孫權/曹操/劉備/赤壁地点＋赤壁事件
   same_occurrence，随 `01a08997` 发布）＋历史曹操 batch（随 ZZ v1
   `01a088e7` 发布）；已裁决未发布：ZZ2 的 12 组（canonical 稳定性
   fail-closed 终局保留）。缺失：督軍任命等从未开出、系统矩阵、
   已发表后 event 归并语义（上报项）。不得合称为完整闭环。

## 13. Recall 契约裁决（owning-layer decision，有记录、可审计）

问题（真实证据，见 §12 负发现 1）：validator 为纯结构检查，
骨架 bundle（先主傳：12591 字仅 1 entity/1 event/1 claim/2 mentions，
译文实含曹操 37× 等）可以通过；修正轮“修好唯一报错”进一步激励最小修复。
T19 不能以结构 PASS 代替召回判断。

裁决（T01 拥有层 `chapter_contract.py`，契约只增观察、不增门限）：

1. **拒绝硬召回下限**（如“每章至少 N entities”）：可被 padding 轻易 game；
   对天然稀疏章误伤；阈值本身无文本依据，属武断语义。维持 validator
   `passed`/`count` 语义不变——不放宽、不收紧通过线。
2. **实现召回可观察性**：validation report 增加 `recall` 观察节
   （`chapter_chars`、`translation_chars/blocks`、entity/event/claim/
   mention/resolved/unresolved/record_sources 计数、`per_1000_chars`
   密度；report `version` 0.1→0.2）。该节永不影响 `passed`/`count`；
   通过既有 Studio projection 原样进入 attempt evidence，
   operator 与独立 reviewer 按章读数判断召回，不再静默。
3. 修正轮最小修复激励如实记录为已知动态，不在本轮另设计数器对抗；
   召回判断归人工核对（本记录 §12 方法）。

实现：`bundle_recall_observations`＋`_report` 接线（`chapter_contract.py`），
focused tests（`RecallObservationsTests`：fixture 计数、no-floor 类别不存在、
畸形候选零值）。验证：contract/extraction/wiring＋gate 全过（见 T19 台账）。
负证据保留：骨架 bundle 原件在 DB（job 1 artifacts）与 §12 中原样保留，
未删除、未重写。

本轮结论：NOT_PASSED（裁决本身不转正任何案例；0/13 保持）。

## 14. 真实验证轮次 5024be17（recall 观察＋两书发布，verdict 仍为 NOT_PASSED）

- 候选：`5024be17c2df8fc64fca5c72c838b366990b20c`（§13 recall 观察节，
  report v0.2；其余代码同 v6 prompt）。镜像 `loom-chronicle:t19-5024be17`
  （SHA 校验一致），新 project（端口 8086）＋新数据/证据目录
  `/srv/loom-t19-evidence/5024be17/`，模型 `gpt-5.6-luna`。
- recall 观察 live 验证：先主傳 correction recall
  entities=10/events=7/mentions=10（0.79/1000字），译文 16519 字——
  富 bundle 可见，不再静默；API run meta 原样携带 recall（证据到位）。
- 三國志 job（`4252de57`）：chunk 0 run1 通过、chunk 1 run2 通过
  （run1 全员 hedge 违规被修正）、chunk 2 通过；assemble 通过；
  resolve 开出 22 个同书 pair（19 人＋益州/荊州/夏口 3 地），operator
  按原文逐条裁决 22/22 same_entity（决定文件已存档），resume 后
  resolve→publish→present 全完成；publication `01a088b2`（三章，
  artifacts `4ca75066`/`588cfbc3`/`3f93574f`）。
- 通鑑 job（`1fe9b575`）：run1 hedge、run2 transport 空回包、run3 2 anchor、
  run4 全员 hedge、run5 通过；resolve 开出 1 个跨書 batch（先主傳曹操↔
  通鑑曹操），operator 裁决 same_entity（第二来源覆盖首例）；publish 完成，
  publication `01a088e7`（artifact `5f6e2b43`，64 块 14591 字）。
- 四章 Reader：API 全文＋SHA＋引用计数；真 chromium 渲染 DOM
  （18397/8464/6749/16440 字）首尾标题齐全，截图已归档。
- 旧失败全保留（855a1dc0 等 5 个 project 容器与 DB 原位；job 1–5 终局不变）。
- 本轮结论：NOT_PASSED。待独立 reviewer 转正 13 案（0/13 保持）与对账；
  未关闭 T19/#548；PR body 无 close 语义。

## 15. 第二通鑑导入与 canonical 稳定性发现（verdict 仍为 NOT_PASSED）

- 新通鑑 document＋revision（同冻结字节 `b9831c28`，`duplicate=False`）
  ＋ job 2（`09870dff`）：chunk run1 通过；resolve 对 catalog v2
  （SG 已发布 3 章＋ZZ v1）开出 12 个 review（10 entity＋2 event），
  operator 按原文逐条裁决——10×`same_entity`（荊州/諸葛亮/劉備/甘寧/
  赤壁/周瑜/曹操/孫權/劉表/江陵）＋2×`same_occurrence`
  （赤壁之戰↔赤壁火攻擊敗曹操；火攻曹軍水軍↔赤壁火攻擊敗曹操，
  均为建安十三年赤壁火攻破曹同一战役/战斗），12/12 resolved。
- publish 按设计 fail-closed（新证据类）：
  `Event publication would collapse existing canonical IDs
  [01a088b2-7151-...] via [c1rev-4d06...:evt_001003, ...:evt_001004,
  c1rev-556d...:evt_000006]`——已发布的 SG canonical 事件不可事后归并，
  整单 publish 原子回滚。entity 的 10 组 same_entity 不触发此错
  （与 ZZ v1 的曹操 batch 已发布成功一致）；event same_occurrence
  在首书发布后不可再发布，属已发表身份不可变语义，
  未降级裁决迁就发布，未重设计（上报定夺）。job 2 作 terminal 证据保留；
  ZZ 已发布产物（`01a088e7`）不受影响。
- Studio 真实浏览器流闭环：测试机装 node＋playwright chromium
  （环境变更，未进仓库）；canonical `chapter-reader-smoke.mjs`
  对 4 个已发布章全部 PASS（64/43/16/10 块全渲染、原文面板开合、
  直接打开/刷新/移动端）；Studio `/studio/review` 未认证只渲染登录壳
  （服务端强制认证，正确）；认证后审核队列“待处理 0 项”，
  已处理页显示 23＋12 条“已选择：同一实体/同一战役”轨迹，截图已归档。
  （canonical `review-flow-smoke.mjs` 仅 mocked-api，不适用于真实后端，
  故 Studio 交互证据为上述真实登录＋队列＋轨迹；reviewer 可复核。）
- 本轮结论：NOT_PASSED。13 案独立结论 0/13 保持；未关闭 T19/#548。

## 16. 跨書矩阵定义（存在 vs 缺失，单一口径，v8 当前）

已存在（有终局证据，不重复演练）：

| 覆盖 | 内容 | 状态 |
| --- | --- | --- |
| 同书 pair（SG 内，v8） | 22 组（21 entity＋1 event：赤壁之戰 d7397a4b same_occurrence；含劉備/曹操/孫權/周瑜三角与魯肅/程普/孫策/甘寧/呂蒙/劉璋/赤壁/荊州/益州/夏口/南郡/江東），浏览器内真实点击 | 已裁决＋已发布（`01a08997`） |
| 跨書 batch（v8，SG↔ZZ） | 4 entity same_entity（孫權/曹操/劉備/赤壁地点）＋1 event same_occurrence（赤壁之戰↔赤壁之戰），浏览器内真实点击 | 已裁决＋已发布（`01a08997`，与 ZZ 已发布 `01a08975` 链接） |
| 跨書 batch（历史，曹操） | 先主傳曹操↔通鑑曹操 same_entity | 已裁决＋已发布（`01a088e7`） |
| 跨書 batch（历史，ZZ2） | 10 entity same_entity＋2 event same_occurrence | 已裁决、未发布（canonical 稳定性 fail-closed，终局保留） |
| 章内共指建模（v8） | 先主傳 12/12、周瑜傳 19/19、魯肅傳 8/10 mentions resolved（含先主→ent_001 劉備跨度拷贝） | 已发布 bundle 有记录（首次）；剩余 unresolved 与空心章待决 |
| 导入级第二来源 | SG doc2/doc3（jobs 4/5/2）、ZZ doc2（job 2）独立导入事件 | 终局保留 |

缺失（blocker，原样保留，不得视为完成）：

| 缺口 | 说明 |
| --- | --- |
| 系统性跨書 batch 矩阵 | 督軍任命等从未开出；魯肅/程普等 v8 轮未涌现（recall 方差）；无矩阵级覆盖证据 |
| 空心/condensed 译文 | v7 先主傳 0.192、v8 ZZ 0.26、v8 周瑜傳缺关键段（§18）；内容失败 |
| 已发表后 event 归并语义 | ZZ2 证明不可发布；v8 单向 join 可发布——边界已记录，属语义上报项 |
| Studio 浏览器 decision-click | v8 轮 27/27 已完成（见 §17/§18）；canonical review-flow 脚本仍 mocked-only |
| 13 案独立转正 | 0/13 保持；待独立 reviewer |

不得把已发布覆盖合称为完整跨書闭环。

## 17. Studio 浏览器证据边界（精确划分）

- ✅ Canonical 真实后端证据：`chapter-reader-smoke.mjs` 对 4 个已发布章
  全部 PASS（生产 Rust 前端＋真实 API，非 dev server/mock）。
- ✅ 真实 UI 读证据（ad-hoc playwright 驱动，非 canonical 脚本）：
  `/studio/review` 登录壳（未认证）→ 认证登录 → 审核队列“待处理 0 项”→
  已处理页 23＋12 条已裁决轨迹；截图与 DOM 断言已归档。
- ✅ 23＋12 条历史裁决：经认证 API（与 UI 同路由）执行，有终局快照；
  当时非浏览器点击（历史局限，见 §15）。
- ✅ v8 轮 27 条裁决：浏览器内 open/fill/submit 真实执行
  （ad-hoc playwright 驱动，34 before/after 截图＋27/27 FINAL），
  非 mocked、非纯 API。
- ❌ 剩余 unmet（保留）：canonical `review-flow-smoke.mjs` 仍仅
  mocked-api——尚无以仓库 canonical 脚本执行的真实后端 review-flow
  浏览器证据；ad-hoc 驱动已证明 UI 路径可行，但不等同 canonical 覆盖。
  Mocked（review-flow smoke）/ API（历史 23＋12）/ 真实 UI
  点击（v8 27/27）/ 真实 UI 读四类证据在此明确区分，不得混用。
- 本轮结论：NOT_PASSED。13 案独立结论 0/13 保持；未关闭 T19/#548。

## 18. v7/v8 轮：mention 链接建模验证、浏览器真实点击与空心译文发现

- v7（`a517dcd`，prompt：优先 resolve 已确证指代）→ v8（`0bb5c6a`，
  ＋temp_id 001–999 prompt 钉值与校验前置失败，起因 job 2 `ent_1001`
  在 assemble 炸作业；prompt v8，focused tests 99＋gate 15 全过）。
  镜像 SHA 校验一致；新 project（端口 8087→8088）＋新证据目录。
- Mention/bundle linkage 建模验证（v7 生效，v8 保持）：
  已发布 v8 三章 mentions resolved 12/12、19/19、8/10（此前轮次全 0）；
  先主傳 m_001 先主→ent_001 劉備、m_002 曹公征徐州→ent_002 曹操、
  操/羽/飛/亮/璋等全链（surface-as-copy 跨度）；C01 章内共指有 bundle
  记录（首次）。先主傳 entities 20（含劉備/曹操/孫權/關羽/張飛/諸葛亮，
  全繁体）。 expressive §12 C01 行待独立 reviewer 结合本节复核。
- 浏览器内真实 decision-click（v8 SG job，27/27）：
  ad-hoc playwright 驱动（非 canonical 脚本，如实注明）完成
  登录→逐条 open→select decision→填 rationale/confidence→confirm 提交，
  每条 before/after 截图（34 张）＋`browser-decisions.json`；
  API 核验 0 open；终局快照 `reviews-FINAL/` 27/27 resolved
  （22 同书 pair＋5 跨書：孫權/赤壁事件/曹操/劉備/赤壁地点）。
  resume 后 8 阶段全完成，publication `01a08997`（三章）。
  通鑑 v8 job 先行完成并发布（`01a08975`），故 SG 计划含跨書 batch。
- 空心/condensed 译文发现（内容失败，终局保留，不重写已发布产物）：
  v7 先主傳出版物 43 块仅 2412 字（ratio 0.192，孫權/白帝 x0）；
  v8 通鑑 62 块仅 2808 字（ratio 0.26，关键项各 x1，缺卷题行）；
  v8 周瑜傳 3182 字（ratio 0.63，缺左右督任命/陳就/蘇飛段、
  公瑾归一为周瑜）；v8 先主傳 16516 字（1.31）与魯肅傳 5155 字
  （1.43）完整。recall 观察节使空心可见（此前静默），
  但 validator 本身无 fidelity 门——§13 哲学不变（观察不设限），
  空心章的内容失败由人工核对承担（本节），转正仍待独立 reviewer。
- Canonical reader smoke：v8 四章全部 PASS（43/16/10/62 块渲染；
  真 chromium DOM 首尾断言 18718/4510/6666/4762 字＋截图；内容空心不影响
  渲染层 PASS——渲染与内容验收分离，明确记录）。
- 本轮结论：NOT_PASSED。0/13 保持；未关闭 T19/#548。
