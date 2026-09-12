# 0.4 分阶段生产验证记录

对应 [#684](https://github.com/6spot/Loom/issues/684) /
[PR #685](https://github.com/6spot/Loom/pull/685)。本目录同时保留程序机制验证与
真实模型失败，二者分别说明，不能用 fixture 结果替代真实史料验收。

## 真实模型结果

来源为仓库完整《周瑜传》，共 5,018 code points；每个实际请求都带完整章节。
模型始终为 `gpt-5.6-luna`，通过已授权的 CPA Responses 接口调用。共有 1 次
翻译、5 次提取或提取纠错，合计 6 次真实 HTTP 调用。

| 检查 | 耗时 | 实际结果 |
| --- | ---: | --- |
| 真实 Runner + 隔离 PostgreSQL 的纯译文 | 57.695 秒 | 完整返回 4,433 字符；已保存，不因提取失败重译 |
| 同次并行提取 | 154.062 秒 | 完整返回，782 个格式错误；传给模型的 schema 缺少外部定义 |
| schema 闭合后的独立提取 | 62.327 秒 | 完整返回，仍有 17 个格式错误 |
| 补充字段提示的独立提取 | 211.742 秒 | 完整返回，53 个错误；提示误写 `extraction.method=llm`，随后改为 canonical `model` |
| 修正该提示后的独立提取 | 89.809 秒 | 完整返回，仍有 10 个日期结构等错误 |
| 带完整旧结果及错误的一次有界纠错 | 180.013 秒 | 到达总时限，未取得可用文本，明确记录为超时；未继续调用 |

后四次是独立协议验证，只复用已保存的完整 request，不冒充原 job 在更改配置后
恢复。最后一次实际使用生产 `retry_prompt`，其基础提示与上一份已保存提示完全
相同；错误反馈含上一份原始结果和全部校验错误。

**没有完整真实章节被接受，没有公开发布或业务部署。** 本记录不证明历史内容
正确，不关闭 [#586](https://github.com/6spot/Loom/issues/586) 或
[#549](https://github.com/6spot/Loom/issues/549)。未继续执行真实关联、复核、
人物状态审核、综合叙事及四章浏览器验收。

## 程序机制与浏览器验证

分阶段 PostgreSQL 回归使用显式模型 fixture，验证真实执行器、保存、恢复、
审核与发布边界。新回归覆盖格式错误只重试同一节点、完整错误反馈、预算耗尽
后零调用、纠错中断网恢复，以及重试提示超限后仍保存并行译文。

[浏览器结果](browser/result.json) 的 13 项检查通过真实 Rust/Python/PostgreSQL
栈执行，没有 mock HTTP 路由；模型为 fixture。桌面和 390px 窄屏验证完整原文、
模型历史、草稿刷新与隔离、修改后禁止原样接受、底部操作以及保存下一项。截图：
[桌面](browser/desktop.png)、[窄屏](browser/mobile.png)。该 UI 已包含在
`49f01298`，后续修复没有再更改 UI。

## 证据文件

- [run.json](run.json)：实际调用、分层结论和未完成验收。
- [request.json](request.json)：共同的完整自然章请求与来源范围。
- [initial-pipeline-outputs.json](initial-pipeline-outputs.json)：第一次真实 Runner
  的完整保存记录，包括初次请求、译文、提取和校验结果。
- [initial-pipeline-code.json](initial-pipeline-code.json)：该次运行开始时的代码指纹。
- [extraction-probes.json](extraction-probes.json)：后续四次的实际完整提示、原始
  返回、完整校验错误、用量和耗时；省去可从原始 JSON 恢复的重复 `parsed`。
- [files.json](files.json)：上述归档输入、结果和截图的文件 hash；说明文档自身
  不在此 hash 表内。

运行、配置与恢复以 [worker.md](../../../../docs/worker.md) 和
[staged-chapter-production.md](../../../../docs/staged-chapter-production.md) 为准。
此目录是证据归档，不增加另一套生产或部署流程，不保存凭据。
