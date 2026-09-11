# C2-R3-D01 第三轮人物变化链与阶段反例语料

任务：C2-R3-D01（Issue #617），父任务 C2-R3（Issue #550）。本目录只准备第三轮
**逐项可核对的人物阶段案例输入**，供 T01 生成契约与 T15 独立内容验收消费。

## 范围与冻结原件

- 只引用第一轮已冻结的四份完整自然章，不重新下载、不改写、不截取冒充整章，也不
  复制全文到本目录。真实引用由 `test_third_round_cases.py` 对冻结原件重定位。
- 语义与字段遵循 [person-state-reading.md](../../docs/person-state-reading.md)
  §2–3、§9，以及 [review-workflow.md](../../docs/review-workflow.md) 的既有审核边界。
- 第一轮原件、上传材料与 `source-pack.json` 不改；本目录只读它们。

| key | 著作／章 | 文件（相对 `../first-round`） | SHA-256（原始字节） | 字符 |
| --- | --- | --- | --- | ---: |
| `xianzhu-liubei` | 三國志·蜀書·先主傳 | `sources/sanguozhi-032-xianzhu-liubei.txt` | `ea40a7087560fe9e693e6f81cb7d1689704f888a40b5b8a8bf7169ec272994e8` | 12572 |
| `zhou-yu` | 三國志·吳書·周瑜傳 | `sources/sanguozhi-054-zhou-yu.txt` | `63db082c4e763be3b56c87cb56e2bed904af5325e9a498b07d932d3b5af1f43e` | 5018 |
| `lu-su` | 三國志·吳書·魯肅傳 | `sources/sanguozhi-054-lu-su.txt` | `1550e1735f44eda7adb9bf27f4ed2cbc9c2185baf6634400140cd52ac312553d` | 3583 |
| `zztj-065` | 資治通鑑·卷第六十五 | `sources/zizhi-tongjian-065-quan.txt` | `c7f80c6baff73a0caa0bbf365117b9ae91892da590ab3830392deb9bcb46fd38` | 10680 |

第一轮版本、下载字节与规范化规则见 [first-round/README.md](../first-round/README.md)；
本轮不生成新的规范化版本。

## 文件一览

- `cases.json`：13 个真案例（`R3C01`–`R3C13`）＋6 个明确 `synthetic=true` 的边界反例
  （`R3N01`–`R3N06`），共 19 案。每案记录人物、阶段、逐项预期
  （维度／值／关系／操作／限定／明确性／原因码／来源归属）、允许与禁止显示结果、
  以及真实引用或 `refs: []` 空态。
- `walkthrough.md`：逐案核对说明（原文能证明什么、不能证明什么），并标出真实／合成。
- `test_third_round_cases.py`：只读重定位与一致性检查（不触网、不改原件）。

## 数据契约

`schema=chronicle.third-round-person-state-cases`，`coordinate_unit=unicode_code_point`。
`cases.json` 的 `rule` 字段是权威声明，要点：

- `synthetic=true` 的条目**不得**作为史料发现引用；它们要么引用真实原文作为素材并
  主张阶段／契约边界，要么为空态（`refs: []`），不得发明历史措辞。
- 每个真实 ref 的 `quote` 必须恰好在 `[start,end)`（按 Unicode code point），且为文件
  中第 `occurrence` 次出现（从 1 起）；`sha256` 必须等于冻结原件原始字节哈希。
- 每个带 `surface` 的预期项必须在其 `refs[proven_by].quote` 中出现，使案例说明与原文
  可机器对照；不一致时检查失败。
- 全部案例 `evidence_class=human-content-review`：这是人工内容核对预期，不是真实模型、
  真实后端或已发布结果。T01/T15 不得把它当作已完成的模型输出。
- 原因码至少含 `tenure_unproven`、`order_unknown`、`source_disagreement`、
  `attribution_uncertain`、`evidence_uncertain`，另加 `phase_not_reached`、
  `phase_not_begun` 表示未来／尚未开始。

## 覆盖

| 维度 | 真案例 |
| --- | --- |
| 授任（授任者与阶段各有依据） | R3C01 |
| 兼任（两条并存，不压成最高官职） | R3C02、R3C09 |
| 行动角色 vs 长期身份 | R3C03 |
| 转投（定向关系变化） | R3C04 |
| 辞还（奏章自述，只结束对应官爵） | R3C05 |
| 父祖官职不计入本体 | R3C06 |
| 注释／引书归属 | R3C07、R3C12 |
| 推荐（表荐不等于实授） | R3C08、R3C13 |
| 阶段变化／再次领任 | R3C10 |
| 来源分歧（保留双方） | R3C11 |

| 边界 | 合成反例 |
| --- | --- |
| 同年顺序未知 | R3N01 |
| 跨章回溯不切换阶段 | R3N02 |
| 明确结束后再次任职另起段 | R3N03 |
| 未来头衔不得提前 | R3N04 |
| 空态「暂无记载」非虚构身份 | R3N05 |
| 对立来源不由模型／导入顺序裁定 | R3N06 |

## 可重复检查

```bash
python3 -m unittest discover -s apps/chronicle/corpus -p 'test_third_round_cases.py' -v
python3 -m unittest discover -s apps/chronicle/corpus -p 'test_first_round_pack.py' -v
```

定位测试只证明引用可复查、案例说明与原文一致，不证明历史结论为真；逐案语义判断仍需
人工内容核对。真实模型／真实后端／发布与阅读联动属于后续任务，本目录不宣称完成。
