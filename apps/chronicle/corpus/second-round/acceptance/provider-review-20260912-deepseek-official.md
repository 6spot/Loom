# 2026-09-12：deepseek-flash 同章输出测试

**完整章节仍未完成，不能评定翻译或抽取质量。** 新模型的小型 JSON 请求成功；
原程序先遇到输出格式不兼容，单独改用 JSON 模式的完整章请求也没有在观察窗口内
返回完整结果。本次没有修改产品实现、写库、审核、发布或部署。

用户指定 CPA 新增的 `deepseek-flash`，并说明该路由使用 DeepSeek 官方 API。
本次确认 CPA 模型目录包含这个名称；没有继续调查其内部路由或索取上游凭据。

| 测试 | 实际结果 |
| --- | --- |
| 原程序：完整章、严格 JSON Schema | 2.836 秒后返回 HTTP 400：`This response_format type is unavailable now`。没有生成候选，用量和费用未报告。 |
| 测试适配：同一完整章、普通 JSON 模式 | 22.838 秒时收到 HTTP 响应头；经过 1,263.151 秒仍未得到完整响应，测试控制器在超过 1,200 秒观察窗口后主动停止请求。没有完整候选、结束原因或用量。 |
| 单独的小型 JSON 请求 | 4.578 秒完成，返回 `{"ok":true,"numbers":[1,2,3,4,5]}`；服务报告输入 80、输出 56、总计 136 token，推理 token 为 0。该请求不能代表完整章或一般推理配置。 |

完整章使用此前同一份《先主传》：12,591 个字符、86 个源块、41 个必需正文块，
包含现存嵌注，没有加入其他章节。执行代码为 `07c6c4044f2cfa2c4418df1b2d5e71c93772f47a`，
candidate 0.2、prompt v6；完整章输出预算 131,072 token，HTTP 响应上限 4 MiB，
单次 HTTP 超时配置 1,200 秒、每次最多一次 HTTP 尝试。

两次完整章测试与此前 DeepSeek 131,072 预算测试的 request 和首稿 prompt 完全一致。
首稿 prompt 为 51,388 个字符，SHA256 为
`2aa8f1972b58fbce1906cf9a16ebe0f15cd4db4037093aa282d766b8838b789f`。
第一次仅更换模型名称；第二次另由临时测试适配器将 provider 的
`text.format` 从 `json_schema` 改为 `json_object`，完整提示、提示内 schema 和
程序端候选／纠错校验保持原样。这项适配尚未进入产品。

普通 JSON 长请求被停止时，Python 堆栈仍在原 provider 的
`response.read(max_response_bytes + 1)` 中等待。当前适配器缓冲完整非流式响应，
本次没有捕获已到达但未返回给调用方的部分线缆内容。因此只能说未获得完整结果，
不能说上游完全没有生成文字。配置的 socket 超时也不等于请求总时长上限；
控制器实际停止时间如上，不能写成服务自动超时或 `max_output_tokens` 截断。

两次整章请求各执行一次语义调用、一次 HTTP，均未进入纠错。小型 JSON 探针另计一次
HTTP；模型目录的只读请求不计为生成调用。小探针的成功和零推理用量不能推定长请求
的用量。所有请求账单费用均未知。

本次确认需要处理 provider 输出格式差异；尚无证据认定语料有问题，也没有证据证明
更换模型已解决长章生成。后续长任务应能报告进度、限制总时长并保存可恢复的结果。
本报告没有实现这些能力。#586、#549 仍未验收；此次也未验证 R3 的 0.3 产物。

证据：

- [原程序运行与格式错误](run-live-r2-20260912-deepseek-official-schema-v6.json)、[完整请求及失败历史](candidate-live-r2-20260912-deepseek-official-schema-v6.json)。
- [JSON 模式运行及小探针](run-live-r2-20260912-deepseek-official-json-v6.json)、[完整请求、实际 prompt 与停止记录](request-live-r2-20260912-deepseek-official-json-v6.json)。
- [live 预检](preflight-live-r2-20260912-deepseek-official-v6.json)：`READY` 只表示预检满足；其中环境默认超时 600 秒，实际测试显式使用上述 1,200 秒。
- [39 项证据核验](verification-20260912-deepseek-official.json)：请求／原文／prompt 一致性、失败历史重放、停止时长、HTTP SHA／大小和小探针实际输出及用量均通过；不属于语义或产品验收。

原程序失败历史已在本地重新验证，重放无差异。JSON 长请求没有形成 extraction
result，不声称其运行历史通过重放或内容校验。原始 HTTP 和私密配置留在受控环境；
仓库记录必要的请求、错误、输出、用量及 SHA，不包含凭据。
