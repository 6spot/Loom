# 完整章节分阶段生产：真实部署闭环（2026-09-13）

**完整《周瑜传》已在真实测试环境经操作员修订和审核后发布，公开历史流可读。**
本次完成 #688 要求的失败排查、部署和继续执行：没有停在超时、来源发布或
后台 completed。当前证据证明单章流程及关键阅读操作能够完成；不证明模型
自动通过、多个独立来源相互印证、四章 R2 或完整 R3 人物体验已经通过。

最终运行程序为 `a9d478afd579e992566f6fdea6629ff45981c7f7`。所有步骤复用
`CHRONICLE_MODEL_TIMEOUT_SECONDS=1800`，即**单次模型调用总时限 30 分钟**，
不是整条任务的完成时限。运行中的配置见
[deployed-runtime.json](verification/deployed-runtime.json)，每次章节调用的实际
超时和耗时见 [observations.json](observations.json)。

## 最终结果

| 环节 | 实际结果与边界 |
| --- | --- |
| 完整自然章 | 原件 5,018 Unicode code points / 14,996 bytes，正文与原注完整保留 |
| 纯译文 | Luna 首次返回 4,356 字符，81.647 秒；和提取并行启动，后续失败没有重译本章 |
| 独立提取 | Sol 首次返回，625.301 秒；包含人物、事件和阶段事实 |
| 关联、复核、局部修正 | 按节点保存和恢复；保留不合法结果、模型异议和操作员修订 |
| 来源内容接受 | 最终再复核输入超限，进入正式内容例外审核；操作员处理全部意见后接受，不能称最终模型复核通过 |
| 人物阶段审核 | 84 项经真实 Studio UI 明确提交：76 supported、8 uncertain |
| 来源发布 | 完整章、19 个译文段、状态与原文锚点发布成功，来源 job completed、待审 0 |
| 综合事实审核 | Luna 提出 12 阶段 / 35 结论；操作员逐条核对后接受 33 阶段 / 64 结论，其中 5 条存疑 |
| 综合正文审核 | Luna 完整旧稿纠错后结构通过；操作员修订为 35 段、2,478 字符，保留 3 个重要入口 |
| 综合发布 | 同一 job 正式 resume 后发布；completed、待审 0；没有重置 claim/调用预算 |
| 公开读回 | 所有 35 段与审核内容确定性编译结果完全相同；64 条结论及其全部公开原文引用逐项核对 |
| 真实浏览器 | 最终部署上 35 项阅读、14 项定位/样式检查通过；人物审核保存记录 11 项、事实保存记录 11 项、正文保存和继续生产 14 项通过 |

[completion.json](completion.json) 固定上述结果及未证明项。
它不以 HTTP 200、JSON 合法、模型相互一致或一张截图代替内容接受。

## 真实来源、模型与入口

来源是仓库的
[`sanguozhi-054-zhou-yu.txt`](../../../first-round/sources/sanguozhi-054-zhou-yu.txt)，
来自维基文库《三國志/卷54》`oldid=2387393` 的完整《周瑜传》。原作公有领域，
维基文库整理文本按 CC BY-SA 使用；保留上传时的来源说明和全部原注。
SHA-256：`63db082c4e763be3b56c87cb56e2bed904af5325e9a498b07d932d3b5af1f43e`。
没有把整本《三国志》送入，也没有用短节选替代自然章。

| 用途 | 本次实际模型 |
| --- | --- |
| 翻译 | `gpt-5.6-luna` |
| 提取、关联、内容复核、局部修正 | `gpt-5.6-sol` |
| 综合 facts / prose | `gpt-5.6-luna` |

章节模型通过已授权 CPA Responses 路由调用，单次输出预算 65,536 tokens；
综合模型输出预算 32,768 tokens。所有模型总超时均为 1,800 秒。
提取与内容复核使用同一个 Sol，**本次不是两种不同模型的独立交叉验证**。
来源及综合审核操作者为获用户授权的验收代理，不是另请的独立史学审稿者。

测试站首页为 `http://127.0.0.1:8092/`，可从孙策渡江、赤壁之战或南郡争夺进入。
固定的赤壁入口：

```text
/history?version=9684d395d97aa5fb28811c3fd18512c3742f2cdda5371734763d5ab020e3ceff&at=hp_56e464ca4a9c46614b7e7f32
```

| 记录 | 固定 ID |
| --- | --- |
| 来源 revision | `af18c491-1ab9-4a5c-ab71-f29a35c92570` |
| 章节 | `ch_6bc2723f42f02d2afa8a9a23` |
| 来源 job | `7f786015-724f-438f-b560-7a220f1a476f`，attempt 6 / max 8 |
| 来源 publication | `01a09988-8b88-79f0-b3ef-eae1b95b4ff5` |
| 人物阶段审核 | `64b744b7-cfe2-4fc3-a899-c05072e3c844` |
| 综合 job | `fe51307c-b5dd-47fe-8b6c-9330b57e0222`，attempt 5 / max 5 |
| facts 审核 | `2c5701bd-09b4-45c2-b522-c125fc913496` |
| prose 审核 | `a960da18-cf4d-4782-a910-acc90596c1ac` |
| catalog | `22b70383e3fc5a966abaa1523d05fb6d7d1c222e4176626857f4f4b01028ca97` |

## 没有丢弃的失败与恢复

| 运行 | 真实 HTTP 调用 | 结果 |
| --- | --- | --- |
| [baseline](baseline/) | 5 | 提取纠错后通过，但关联 mode / 引用仍不合法，failed |
| [source-context](source-context/) | 8 | 保留一次厂商失败；取得完整稿后，复核报告与修订仍有错误，最终 cancelled |
| [luna-structured](luna-structured/) | 4 | 译文完成；三次提取均有不合法来源选择，failed |
| [sol-structured](sol-structured/) | 9 | 翻译、提取、关联、复核、修正和修订后关联均留存，经过内容及人物审核后 completed |

各次 receipt 中的 `completed` 指模型运输完成；节点仍可能因内容不合法为
`invalid`。全部实际调用共用 30 分钟配置，本组没有再次触发 3 分钟超时。
最后一次关联成功后，内容再复核需要 1,106,468 字符，超过冻结的 1,048,576
字符预算，未发出新模型请求。#695 将完整候选和错误送到正式内容例外审核，
操作员逐项處置后恢复；没有降低验证、删掉原文或加大冻结输入预算。

综合任务先遇到重复状态扩大输入的问题。#696 仅在模型视图去除同一来源中
完整字段相同的重复状态，675 行变为 98 个不同状态，原始冻结 context 不变。
首次完整正文又把只适用于抗曹商议的刘备遣使结论放到赤壁交战段，按合同拒绝。
携完整旧稿纠错时输入仍超限，#698 将 98 个状态中重复的 27 种完整 provenance
放入同来源的可还原表；纠错请求为 171,874 字符，满足原有 180,000 字符预算。
随后的 Luna 纠错完整返回并通过结构校验，所有批准阶段均保留。

压缩核对见 [context-row-compaction.json](verification/context-row-compaction.json)
和 [context-provenance-compaction.json](verification/context-provenance-compaction.json)：
原章、译文、222 个依据及每个不同状态/来源记录均保留，未变更冻结 context、
候选、历史失败、每节点预算或发布边界。没有直接写数据库伪造产物；审核和
任务恢复均走正式 Studio API / UI。

## 操作员具体修订

来源内容修订及意见逐项处理见 [operator/](operator/)。人物阶段的 8 个 uncertain
包括江夏太守底本疑文、奏疏称失爵及未明起点、跨季节的回顾时间和家属纪事
顺序，不能将模型处理错误改名为史料争议。

事实审核保留原 35 条候选及全部修订记录。修正周忠与周景的关系、鲁肃被错连
为全琮、“闇同”的句意和错误引用；分开任免、季节、南郡任职、取蜀计划和病卒，
补回家属、音乐、二桥和原注中有归属的记载。229 / 239 年与建安时期分开，
不把建安十三年春的前部大督或九月的记载延伸到全部后续。人物官职和地点控制
只在批准的阶段显示，材料缺失保持缺失。

正文修订保留全部 33 个内部阶段，沿用模型已纠正的刘备遣使段，补入有归属的
曹操书信。校勘与审核说明移到深层依据，不在正文写“底本文字有疑”等提示。
明确与存疑文字分片段，避免一句疑问使整段变灰。精选入口只留孙策渡江、赤壁
和南郡三个；内部细节仍在正文和人物资料里。

原候选、实际提交的最终内容与理由分别位于
[facts-candidate.json](narrative/facts-candidate.json)、
[facts-decision.json](narrative/facts-decision.json)、
[prose-candidate.json](narrative/prose-candidate.json)、
[prose-decision.json](narrative/prose-decision.json)。原始模型响应在
[attempts.json](narrative/attempts.json)，没有用修订稿覆盖。

## 前台实际验收与限制

[history.json](browser/history.json) 记录在已部署真实 Rust/Python/PostgreSQL
服务上的 35 项检查，浏览器请求未被 mock：

- 首页只有审核选出的入口；正文没有事件大标题，原文依据默认隐藏。
- 事件词可轻量预览和主动跳转，保持同一个版本。
- 键盘进入周瑜详情时阶段一致，返回同一段和版本。
- 鼠标滚动从随孙策渡江到居巢阶段，周瑜从“效力：孙策”变成“官职：居巢长”。
- 继续向下自动读取下一页，最终到周护纪事和“已读到当前收录的末尾”；入口
  没有把后续内容筛掉。
- 公开原文窗口可展开整章，5,018 字符与上传文件逐字相同。
- 390px 人物面板、320px 正文与面板可用，320px 无横向溢出；无浏览器 pageerror。

另在 [visual-live.json](browser/visual-live.json) 完成 14 项真实检查：1440px 与
320px 下，赤壁和皖县段的 URL、当前段、人物阶段在布局稳定后仍一致，页面无
横向溢出；周瑜的“中护军”和存疑的“江夏太守”同时存在，分别带实心/空心
标记及不同颜色，没有把整个人物一起变灰。对应
[桌面状态](browser/uncertain-state-viewport.png)、
[窄屏状态](browser/uncertain-state-viewport-320.png) 和
[窄屏正文](browser/reading-viewport-320.png) 保存为实际视口截图。

最后补查曾发现 320px 赤壁入口自动退到前一段：日期换行推移正文，阅读控制器
没有收到布局变化；窗口变宽时还受到浏览器原生锚定的重复补偿。#700 复用唯一
控制器维护阅读点、计算完整固定栏高度，并移除页面自己的补页补偿。旧代码的
真实失败与新增浏览器回归保存在
[reading-layout-regression.json](verification/reading-layout-regression.json)；没有
用最初的通过报告覆盖这个失败。合并部署后重新执行了上面的 35 + 14 项检查。
截图采用实际视口：全页捕获曾改变临时布局并干扰紧随其后的键盘操作，改用视口
捕获后，同样的人物阶段和返回断言连续五次通过，没有放宽断言。

[deployed-ui-assets.json](verification/deployed-ui-assets.json) 证明测试站实际服务的
JS/CSS 与已提交构建逐字相同；[post-deploy-job-check.json](verification/post-deploy-job-check.json)
记录升级前后两个任务的 attempt、输出数、全部阶段及已存章节结果未变，仍均为
completed、待审 0。本次界面部署没有重新调用模型或重置任务。

实际查看了 [首页](browser/home-live.png)、[正文](browser/history-desktop.png)、
[人物页](browser/person-page-desktop.png)、[窄屏正文](browser/history-mobile-320.png)、
[原文](browser/source-context-live.png) 和审核截图。
这也发现了尚未达标的产品界面：人物详情仍落在旧资料展示，包含内部协议词、
原始 Claim/Source/Resolution；主阅读和人物状态处露出 `p_east` 等技术 ID。
人物简介与独立经历体验未在本次生成/验收，不能把阶段框及返回成功算作完整
R3 人物页通过。该缺口由 [#699](https://github.com/6spot/Loom/issues/699) 接续
R3 页面与真实体验验收处理。

本次仍只有一个完整来源，不证明跨来源核对、多模型独立交叉验证、所有未知
任期、再次任命、分歧样例或整部历史覆盖。正文只有本次发布范围，跨生产批次
自动拼接、背景图配置和人物完整生平不在此证明中。#586/#549 及 R3 的内容与
体验缺口保持原有验收边界，未因本次单章成功关闭。

## 程序修复、检查与归档

[delivery-prs.json](verification/delivery-prs.json) 记录已合并修复：#687 全局超时，
#689 编号旁原文，#691 多处局部修订，#692 来源/关联语义校验，#693 无效修订
在关联前进入审核，#694 窄屏操作区，#695 输入超限后的内容例外，#696/#698
无损减少模型输入重复，#697 人物状态来源查看及保存后恢复，#700 动态布局下
的历史阅读位置与人物阶段保持一致。

#698 的 16 项叙事合同测试和 3 项 PG18 综合流程回归通过；#697 前端全套 337
项测试通过，最后防护调整后的相关 16 项、构建与 dist smoke 复验通过。
#700 的 337 项前端测试、6 组阅读组件的 272 项浏览器断言、新增综合历史页面
回归、构建与 dist 检查通过；Rust 1.97.1 的 59 项 server 测试、fmt、clippy 通过。
[verification/](verification/) 保存 #695–#698 及 #700 的 CI 结果。
这些单测、PG 回归和 CI 浏览器使用明确的模型 fixture，证明机制；上面的
生产结果及 `browser/` 使用真实模型产物，二者分别记录。

四组来源归档均含 `plans.json`、`attempt-metadata.json`、`results.json`。
attempt metadata 删除了完整 prompt/input，仅为带原输出 hash 的投影，不能
拿投影 JSON 的 hash 冒充原记录 hash。完整模型返回、失败及审核包在结果中
保留；全量请求仍在原测试环境留存。本目录不包含 API key、密码或认证头。

综合 outputs 中还有现有 worker 收尾写入的 `fake-pipeline-result` 历史命名
标记，它只含 worker 版本与阶段名称，不是正文、模型回答或发布产物。实际
模型记录是前面的 `narrative-*-attempt`，真实发布的全部内容与审核结果另经
确定性编译和公开 API 读回验证，不以这个收尾标记判定内容来源。

[file-manifest.json](file-manifest.json) 列出全部归档文件的字节数和 SHA-256。
运行和恢复的操作规则仍以 [worker.md](../../../../docs/worker.md)、
[分阶段生产合同](../../../../docs/staged-chapter-production.md)、
[综合叙事合同](../../../../docs/source-corroboration.md) 与正式部署指南为准。
