# 多史料核对的真实案例

`cases.json` 固定 14 个真实案例，全部引用 first-round/sources 的完整传记文件；
没有合成历史文本。每处引用记录文件 SHA-256、Unicode code point 起止坐标和
原文，测试验证文件未漂移、引用可重定位。每案的 allowed、forbidden 和 reason
记录本轮对原文的内容核对；机器重定位通过不能替代后续编辑审核。

《先主传》《周瑜传》《鲁肃传》同属《三国志》。它们可以互相补充，不按篇数
算独立见证。正文、裴松之注文、所引《江表传》与书信说话人分别保留归属。

| 覆盖 | 案例 |
| --- | --- |
| 同书互见、过程补充、未提及非反证 | alliance_same_work、fire_details |
| 当事人自述、实际争议、评论与事实分开 | cao_letter、liu_hesitation、su_strategy |
| 兼任、阶段、未知日期、身份维度 | concurrent_offices、zhou_unknown_year、yizhou_transition、jingzhou_partition、hanzhong_titles |
| 同名异地、转引措辞不同、局部引用支持范围 | baqiu_places、su_succession、short_quote_scope |
| 原始细节不自动成为导航，后人事迹不能提前 | curated_navigation |

这不是生产文章，也不把字符串匹配当历史真假判定。错引用、阶段越界、行动
伪装状态、未知 ID、回顾段冒充发生锚点等机制反例另由 persistence 合同测试
和 worker PostgreSQL 测试承担，使用明确标注的合成模型输入。

真实端到端运行的操作与限制见 [内容生产合同](../../docs/source-corroboration.md)
和 [worker 开发指南](../../docs/worker.md)。人物完整生平、跨批次全历史拼接及
背景资产与新叙事位置的配置不由这些局部案例宣称完成。
