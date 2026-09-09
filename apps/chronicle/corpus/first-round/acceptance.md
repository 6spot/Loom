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
