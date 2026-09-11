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
| job | `dd993219-…7ff722`（4 次 job attempt） | `6ad9112d-…6e9e`（2 次 job attempt） |
| 发布 unit / group | 66 / 5 | 64 / 1 |
| narrative_time 模式 | events 25，unknown 37，mixed 2，inherit 2 | unknown 64 |
| 非 unknown 的 `year_key` | 0 | 0 |
| 正文事件词 span（`segments[].kind=="event"`） | 0 | 0 |
| `context_entities` | 0 | 0 |
| 章节完整 | 3 章开篇+结尾均在 | 全章开篇+结尾均在 |

正文本身完整、可读：66+64 个 unit 覆盖四章，开篇与结尾文本均在
（见 `run-live-r2.json` 的 `streams[].job_evidence` 与正文样本）。

## 真实内容缺陷（保留原失败证据）

1. **0.2 生成反复 fail-closed**。三國志 job 第 1、2 次 attempt 的 chunk 1
   分别因既有合同规则失败并被拒绝：
   - `reading_time: reading.units[N] inherit mode must not carry current_event_refs`
     （`reading_contract.py:890`）；
   - `chapter: anchors: mention 'm_008' quote occurs 0 time(s) … occurrence=1 was requested`。
   直到第 4 次 job attempt 才通过；資治通鑑也用了 2 次。原始错误见
   `run-live-r2.json` 的 `streams[].job_evidence.chunk_runs[].error`。
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

## 后续

发现属生成/投影合同问题，按任务边界交由相应叶修复并重新验证受影响合同
（生成侧见 T03 联合章节生成，时间/事件/上下文投影见 T04/T05/T07/T14），
修复后由 T17 重跑本复核。不得以 fixture PASS 或本文件的部分结论替代
第二轮验收。
