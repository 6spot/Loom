# C2-R2-T17 真实章节阅读与第二轮内容复核

任务：C2-R2-T17（[GitHub #586](https://github.com/6spot/Loom/issues/586)，
Multica LM-39），父任务 C2-R2（#549）。本文件记录**真实 provider 现场运行**的
内容复核结果，是独立内容审核的输入；机器可读结果见同目录
[`run-live-r2.json`](run-live-r2.json)。

结论（截至本次运行）：**四章正文均完整可读，但第二轮阅读语义（叙事时间、事件
导航、当前人物地点）未通过真实内容验收**。本轮不成立，需由相应叶修复后重跑。

## 复核方法

- 环境：`second_round_gate.py --mode live` strict preflight 返回 `READY`
  （`/tmp/chronicle-r2-live/manifest.json`），随后在隔离 Compose 栈
  （PG18 + Rust `chronicle-server` + Python `read_api` + durable worker）
  上用真实 `gpt-5.6-luna` 运行 0.2 联合章节链。
- 数据：T02 冻结的四个完整自然章（三國志·先主傳/周瑜傳/魯肅傳 +
  資治通鑑卷65），经 Studio 上传、生成、审核（实体/事件消解复核）、发布。
- 读回：只经公开 `reading-streams`/`units`/`groups`/`locate` HTTP 边界，未用
  fixture 或源码字符串代替。
- 复核点来自 `../reading-cases.json`（R2C01–R2C15 真实点，R2N01–R2N03 合成负例）。

## 运行事实

| 项 | 三國志（3 章） | 資治通鑑卷65（1 章） |
| --- | --- | --- |
| 原件 sha256 | `a5dc345f…36076` | `b9831c28…e18bd` |
| revision | `32dc1f0f-8e0b-4e4a-ba85-5f6fb2156910` | `5883698e-b051-4ab9-9c87-c940f09d142e` |
| job | `dd993219-…7ff722`（claim 4＝retry 2＋resume 1） | `6ad9112d-…6e9e`（claim 2＝retry 0＋resume 1） |
| 发布 unit / group | 66 / 5 | 64 / 1 |
| narrative_time 模式 | events 25，unknown 37，mixed 2，inherit 2 | unknown 64 |
| 非 unknown 的 `year_key` | 0 | 0 |
| 正文事件词 span（`segments[].kind=="event"`） | 0 | 0 |
| `context_entities` | 0 | 0 |
| 章节完整 | 3 章开篇+结尾均在 | 全章开篇+结尾均在 |

正文本身完整、可读：66+64 个 unit 覆盖四章，开篇与结尾文本均在
（见 `run-live-r2.json` 的 `streams[].job_evidence` 与正文样本）。

## 真实内容缺陷（保留原失败证据）

1. **0.2 生成反复 fail-closed**。三國志 chunk 1 的前两次 claim 分别因既有
   合同规则失败并被拒绝：
   - `reading_time: reading.units[N] inherit mode must not carry current_event_refs`
     （`reading_contract.py:890`）；
   - `chapter: anchors: mention 'm_008' quote occurs 0 time(s) … occurrence=1 was requested`。
   第三次 claim 才通过。原始错误见 `run-live-r2.json` 的
   `streams[].job_evidence.chunk_runs[].error`。

   **claim 与 retry 口径核对**：`run-live-r2.json` 记录三國志 `claim_count=4`、
   `max_attempts=3`，二者不矛盾也不代表 retry 超限：
   - `claim_count` 是 `ingestion_jobs.attempt` 的原始 claim 计数；
     `control_plane.retry_job` 仅在 `attempt >= max_attempts` 时拒绝重试，本次
     retry 只用了 2 次（claim 2、3），未越界；
   - 第 4 次 claim 是 `needs_review` 审核后的 `resume`（`resume_job` 不占用
     retry 预算），故三國志＝retry 2 + resume 1 = claim 4，資治通鑑＝retry 0 +
     resume 1 = claim 2；
   - T03 章节纠错上限 `ChapterLimits.max_correction_rounds` 固定为 1，单次 claim
     内最多 2 次模型尝试（initial + 1 correction）后 fail-closed，对应错误串
     “failed closed after 2 attempt(s)”；三者是不同计数器（见
     `run-live-r2.json.generation_limits`）。
2. **叙事时间全部未解析**。两部的所有 130 个 unit 的 `year_key` 都是
   `unknown`/`mixed:unknown`，包括資治通鑑中明写的
   `孝献皇帝庚建安十一年（丙戌，西元二〇六年）`（`units[4]`，mode `unknown`）。
3. **正文无事件词 span**。`segments` 只有 `text`，`kind=="event"` 为 0，
   浏览器事件词入口与 hover/触屏预览没有数据。
4. **无当前人物/地点**。所有 unit 的 `context_entities` 为空，
   “当前片段人物地点及角色支持”无从呈现。
5. **事件 id 不可公开解析**。`narrative_time.event_refs` 是来源本地
   `evt_000001` 形式；公开 `reading-events/{id}/preview` 要求 canonical UUID，
   且没有事件 span 可提供 canonical target，事件返回原 unit 无法演示。

## 复核点结论

| 点 | 结论 | 依据 |
| --- | --- | --- |
| R2C01 周瑜傳同章时间推进 | 失败 | `year_key` 全 `unknown`，无年份承接 |
| R2C02 战后时间推进 | 失败 | 同上 |
| R2C03 周瑜傳回溯不入时间轴 | 未验证 | DTO 无事件 span/回溯 relation |
| R2C04 通鑑回溯 | 失败 | 卷65 全 `unknown` |
| R2C05 跨来源同一事件（赤壁） | 失败 | 无 canonical event/targets |
| R2C06 跨来源同一任命 | 失败 | 无 targets |
| R2C07 地点层级 uncertain | 失败 | `context_entities` 空 |
| R2C08 先主傳《典略》注归属 | 未验证 | 注文在译文中作正文出现，无注解归属面 |
| R2C09 周瑜傳《江表傳》注 | 未验证 | 同上 |
| R2C10 卷65馬超仅背景 | 失败 | `context_entities` 空 |
| R2C11 建安十一/十二/十三年分组 | 失败 | 卷65 只有 1 个 group 且全 `unknown` |
| R2C12 史論归属 | 失败 | 卷65 无事件/时间 |
| R2C13 跨章复现（赤壁） | 失败 | 无跨来源事件关联 |
| R2C14 同章称谓共指（先主/備、公瑾、子敬） | 未验证 | 仅有同名 surface 的消解复核，无 claim/context 面证明共指 |
| R2C15 首尾完整 | 通过 | 四章正文开篇与结尾均发布可读 |
| R2N01–R2N03 合成负例 | 未执行 | 负例由离线 harness/组件 fixture 覆盖，本次 live 未重放 |

通过 1 / 失败 10 / 未验证 4（含 3 个合成负例）。

## 未验证项（不得当作已验收）

- 真实内容的人工或独立强复核者结论仍待确认。
- 真实桌面/键盘/触屏/窄屏走查与事件返回原 unit 未执行：发布内容缺少事件
  span 与 context，走查只会重复观察到同一缺失。
- 真实 provider 的 token 用量/成本未由 gate 采集，仅有调用时长（各 stage
  时间戳见 `run-live-r2.json`）。

## 归属交接（required ownership handoffs）

缺陷按任务边界交由下列叶修复；本文件与 `run-live-r2.json.ownership_handoffs`
是交接记录。**在这些修复交付、并在全新隔离环境重跑 live、且独立内容复核通过
之前，不得声称 LM-39 验收通过。**

| 归属 | Issue | 缺陷 |
| --- | --- | --- |
| C2-R2-T03 完整章联合生成 | LM-25 / #572 | `inherit` 单元携带 `current_event_refs`、anchor occurrence/block 不匹配、反复 fail-closed；accepted 阅读单元缺 event span/context 输出 |
| C2-R2-T04 注解 remap/时间分组 | LM-26 / #573 | `year_key` 全未解析（unknown/mixed:unknown）、无年分组、来源本地 event ref 未 remap 成 canonical 公开 id |
| C2-R2-T05 阅读 stream 持久化 | LM-27 / #574 | 已发布单元无 event span、无 `context_entities` |
| C2-R2-T07 locate/分页 | LM-29 / #576 | 需在有效时间/事件索引存在后重验 locate/分页 |
| C2-R2-T08 事件预览/反查 | LM-30 / #577 | 来源本地 event id 与 canonical 公开 id 的 preview/targets 及返回原 unit 合同 |
| C2-R2-T14 当前片段上下文 | LM-36 / #583 | active unit `context_entities` 为空，人物/地点无从呈现 |

T13/LM-35 是这些字段的下游 UI 消费方，不是缺失生产数据的首要归属。

## 回归证据

本次失败的 live 运行作为**回归证据保留**（`run-live-r2.json`，
`acceptance_claimed=false`）：修复后必须在全新隔离环境重跑，四章、12+ 真实
核对点、事件/其他来源/原文返回、桌面/键盘/触屏/窄屏流程与独立内容复核全部
通过，才可进入 LM-39 验收。不得以 fixture PASS 或本文件的部分结论替代第二轮
验收。
