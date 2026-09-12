# C2-R3-T15 逐案人物阶段与阅读复核

结论：**第三轮真实内容与体验验收未通过。** 本次是 live provider / live product
stack 的真实失败，不是 fixture 结果。失败发生在第一份完整上传的第一章 0.3 抽取，
发布边界之前；所以不能从被拒绝候选推断任何人物阶段已经进入产品。

## 分层结果

| 层 | 结果 | 现场证据 |
| --- | --- | --- |
| live preflight | READY | clean candidate、真实 provider 配置、完整 source pack 与 Compose config 均通过 |
| 来源 0.3 生成 | FAIL | claim 1 为 30→5 错，claim 2 为 13→1 错；claim 3 初稿 9 错、纠错 transport failure |
| 来源身份审核 | BLOCKED | 没有生成可审核的冻结候选 |
| 来源阶段依据审核 | BLOCKED | 没有 `chapter_state_evidence` package；没有操作者决定 |
| 来源发布 | BLOCKED | assemble / resolve / publish 均未执行 |
| 综合 facts 审核 | BLOCKED | 无已发布来源，未创建综合任务 |
| 综合 prose 审核 | BLOCKED | facts gate 未开始 |
| 最终读取／人物页／原文返回 | BLOCKED | 无 history version / paragraph / phase / publication anchor |
| 浏览器体验与截图 | NOT_RUN | 无可固定的真实发布版本；不以 fixture 页面替代 |
| synthetic 反例 | NOT_RUN | 未向 live 发布投影注入 synthetic 数据 |

## 真实案例

`BLOCKED` 表示真实史料核对点存在且原文定位仍有效，但本次没有可发布的模型产物，
不能把 source pack、被拒绝候选或 D01 预期当作产品结果。

| 案例 | 结果 | 阻断位置 |
| --- | --- | --- |
| R3C01 周瑜授建威中郎将 | BLOCKED | 《周瑜传》所在后续 chunk 未运行 |
| R3C02 周瑜兼任偏将军／南郡太守 | BLOCKED | 《周瑜传》所在后续 chunk 未运行 |
| R3C03 前部大督只作行动角色 | BLOCKED | 《周瑜传》所在后续 chunk 未运行 |
| R3C04 刘备去楷归谦 | BLOCKED | 《先主传》0.3 候选被合同拒绝，未发布 |
| R3C05 刘备上还印绶 | BLOCKED | 《先主传》0.3 候选被合同拒绝，未发布 |
| R3C06 父祖官职不归周瑜 | BLOCKED | 《周瑜传》所在后续 chunk 未运行 |
| R3C07 《江表传》裴注归属 | BLOCKED | 《周瑜传》所在后续 chunk 未运行 |
| R3C08 曹操表刘备为镇东将军 | BLOCKED | 《先主传》0.3 候选被合同拒绝，未发布 |
| R3C09 刘备左将军／荆州牧并存 | BLOCKED | 《周瑜传》所在后续 chunk 未运行 |
| R3C10 先主复领益州牧 | BLOCKED | 《先主传》0.3 候选被合同拒绝，未发布 |
| R3C11 荆州刺史来源分歧 | BLOCKED | 《先主传》0.3 候选被合同拒绝，未发布 |
| R3C12 裴松之后论不并入当时状态 | BLOCKED | 《周瑜传》所在后续 chunk 未运行 |
| R3C13 先主表刘琦为荆州刺史 | BLOCKED | 《先主传》0.3 候选被合同拒绝，未发布 |

真实案例：PASS 0 / FAIL 0 / BLOCKED 13。此处没有把生成合同失败重写成 13 个内容
`FAIL`：它们没有到达可逐案审查的发布候选；实际生成失败单独保留在上表和 manifest。

## synthetic 反例

| 案例 | 结果 | 说明 |
| --- | --- | --- |
| R3N01 同年顺序未知 | NOT_RUN | live 失败后未注入 synthetic 数据 |
| R3N02 跨章回溯不切换阶段 | NOT_RUN | 同上 |
| R3N03 明确结束后再次任职 | NOT_RUN | 同上 |
| R3N04 未来头衔不提前 | NOT_RUN | 同上 |
| R3N05 无材料空态 | NOT_RUN | 同上 |
| R3N06 对立来源不由导入顺序裁定 | NOT_RUN | 同上 |

synthetic：PASS 0 / FAIL 0 / NOT_RUN 6。T14 fixture PASS 不能填入本表。

## 保留的真实失败

首次初稿校验共 30 项，覆盖 anchor、时间原文 grounding、译文覆盖、事件参与者、
`reading_time` 模式、阶段 source selection 与 phase cardinality。纠错稿把它们降到
5 项，但仍未修正：

1. `ent_003` 的第二个 record source 指向 `b_027`，实际唯一原文位于 `b_039`；
2. `ent_006` 的第二个 record source 指向 `b_013`，原文第一次位于 `b_011`；
3. `t_001` 长 15,507 code points，超过 8,192；
4. 上述两个错误又出现在 `reading.units[0].context_entities` 的 source selection。

显式第二次 claim 的初稿有 13 项，纠错后只剩
`reading.units[9].context_entities[0].source_selections[1]` 的 quote 在全章也找不到。
错误数量下降不等于 accepted；该 run 仍由同一 0.3 contract 拒绝，且与首次 run 的
response hash 一起保留。

最终允许的第三次 claim 初稿仍有 9 项；纠错请求已形成固定 prompt hash，但 provider
响应没有 output text，故没有 correction response hash。attempts 耗尽后 job 标为
`needs_review`，实际 open review package 为 0；这不是来源审核已开始，更不能人工越过
被拒绝候选。

失败归属：真实模型 0.3 联合生成／纠错（C2-R3-T02 及其 prompt/contract 适配），以及
最后一次纠错的 provider transport（无 output text，单独分类）。
contract 正确拒绝错误产物；审核、发布、API 和 UI 没有观察到下游产品缺陷，只是被
上游失败阻断。修复后必须从全新隔离库重跑全部四章与 19 案，不能复用本次失败库宣布
通过。

## 明确未验证

- 没有真人完成来源身份、阶段依据、综合 facts、综合 prose 四类决定。本次没有任何
  自动决定，也不把 Executor 的检查写成真人签字。
- 没有最终 `version / paragraph_id / phase_id`，故正式 HistoryPage、独立人物页、
  原文 publication/anchor、刷新／回退／段内偏移均未验证。
- 没有真实移动端、触屏、键盘连续操作和截图。无发布版本时拍空页面不能构成证据。
- 《周瑜传》《鲁肃传》和《资治通鉴》没有开始真实 0.3 抽取；完整 source pack 的 hash
  已通过 preflight，但不能据此宣称生成或内容覆盖。
