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
- `python3 apps/chronicle/acceptance/first_round_gate.py --mode fixture ... --allow-dirty`
  —— PASS：2 works（三國志 3 章＋通鑑 1 章，plan/切片绑定/接受/装配全经真实入口），
  10 故障注入全部 fail-closed，pair 初始 uncertain 且阻塞、batch 默认 uncertain。
  **该 PASS 明确标注 `fixture_only`，不是 live 内容证明。**
- live 探针（非交互 stdin，如实拒绝）：
  `python3 apps/chronicle/acceptance/first_round_gate.py --mode live ... < /dev/null`
  —— FAIL（符合预期）：`live mode requires an interactive terminal: stdin is not a TTY,
  so no operator could resolve blocking reviews in Studio`。
  证明 live 入口在无人值守环境下 fail-closed，不会静默自动审核。
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
- 12 定位案例独立结论：**0/13**（全部 pending，不伪造结论）。
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
