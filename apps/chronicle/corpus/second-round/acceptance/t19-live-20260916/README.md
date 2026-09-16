## T19 真实资料与闭环验收证据（2026-09-16）

本目录是 LM-80 在候选提交 `9c7bccd5f5937f37de613fb00e8a90e3c5b70892` 上的验收交付。它把真实 provider 运行、当前 staged gate、以及背景素材真实浏览器 smoke 分开记录；fixture PASS 不被当作真实内容质量通过。

### 真实资料运行：到抽取失败并闭环留证

在新库中通过产品 Studio API 上传完整原始资料：

- 《三國志·蜀書·先主傳》：`ea40a7087560fe9e693e6f81cb7d1689704f888a40b5b8a8bf7169ec272994e8`，37,474 bytes，12,572 normalized chars；Wikisource oldid `2583378`。
- 《三國志·吳書·周瑜傳》：`63db082c4e763be3b56c87cb56e2bed904af5325e9a498b07d932d3b5af1f43e`，14,996 bytes，5,018 normalized chars；Wikisource oldid `2387393`。

`t19-live-execution.json` 记录 source manifest hash、revision/document/job、每个步骤的 model/profile、全局 1,800 秒 timeout、attempt duration、usage、输出 hash、validation errors、失败原因和 publication IDs。四个产品 job 共完成 12 次真实 provider attempt：初始 Luna profile 两章各运行一次，随后交换为 Sol executor / Luna reviewer 并以 fresh child run 重跑两章。四个 job 都在 extraction fail-closed；translation 输出已留证，但 0 章进入 review、接受或发布。

这次结果明确标为部分失败，而不是完成：自动通过内容、明确异议、仅异常人工处理、连续 edition 阅读、人物主线、真实资料背景和发布 ID 均为 `NOT_REACHED`。失败条目包含复现、期望、实际、owner 和 evidence 路径；原始模型输出以本目录 `model-outputs/` 保存，产品 output route 仅在本次运行期间可读。未提交任何凭据。

失败摘要：

| 阶段 | 结果 | 证据 |
| --- | --- | --- |
| Luna 初始 profile | 两章 extraction 在有界重试后 invalid/failed，分别记录 72/63 与 29/25 个校验问题 | `t19-live-execution.json` 的 `jobs[0:2].attempts` |
| Sol fresh child profile | 先主传 extraction 一次 invalid 后 provider failure；周瑜传两次 invalid，末次仍有 1 个校验问题 | `t19-live-execution.json` 的 `jobs[2:4].attempts` |
| 复跑/切模 | fresh child 的 `parent_job_id` 与 profile swap 可追溯 | `t19-live-execution.json` |

### 当前 staged gate

`fixture-gate-summary.json` 是同一候选提交的当前入口 `apps/chronicle/acceptance/staged_gate.py --mode fixture` 结果：PASS。现有 0.4 gate、负向故障、人物/历史 contract、20 个 focused gate tests 和真实 Playwright browser suites 均通过；浏览器摘要为 reading flow 50、accessibility 25、reading performance 71、person reading 12、person review 6、person performance 5。5,000 units / 1,000 groups 仅为 deterministic synthetic scale。完整原始 manifest 仍由本地 gate 重新生成，摘要见此目录，不能替代真实 provider 内容复核。

### 背景素材真实浏览器 smoke

`background/background-result.json` 和四张截图记录了真实 webapp/API 浏览器流程：未保存候选对 reader 不可见；保存 first→second 的精确范围后仅范围内显示；范围外保持纸张；键盘切换和数值控件有效；重叠、错误 asset version、错误 edition、transport failure 都保留 Studio draft；停用清除公开范围且保留两个候选。候选图由 smoke 脚本在浏览器 canvas 生成，不是模型生成内容。

该部分使用了已发布的 deterministic fixture edition，并经隔离测试栈的当前 webapp/read sidecar 验证；兼容 front binary 来自此前 staged image，未冒充当前 head 的完整生产栈。因此它是背景 API/UI contract 证据，不是历史内容质量证据。

### 尚未完成项

本目录不声称 T19 已完成。真实资料尚未走到 compare/exception review、人工只处理异常、multi-fragment edition publish/read-back、跨时期人物/地点核验或真实资料背景绑定；至少 12 项原创内容检查也因 extraction 未到达而保持未验证。旧的 `staged-live-20260913/` 是旧提交上的单章 operator-reviewed 记录，不能覆盖本次失败或扩展为四章闭环。下一步应由功能 owner 修复既有 `apps/chronicle/worker/chapter_stage.py` 与 provider output contract 的抽取失败，再在新库重跑同一证据结构。
