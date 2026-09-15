# Chronicle 全局历史版本合同

本文件是 Chronicle 跨生产批次连续阅读的应用层合同。它与
`persistence/history_edition_contract.py` 一一对应，供后续 T10（保存与公开
读取）和 T11（连续阅读窗口）消费；本任务不创建数据库表，也不修改
`HistoryPage`。

## 两层不可变对象

“发布叙事片段”（fragment）是一次完整、已审核、已发布的
`chronicle.historical-publication / 0.1`。它仍受单次生产上限约束：一个片段最多
256 个段落。片段的正文、状态和依据仍由片段发布记录拥有。

“全局阅读版本”（edition）是按审核确认顺序排列的片段引用 manifest。它保存
片段引用、接缝审核、全局段落/阶段/结论映射、精选导航和 hash，但不复制另一份
可编辑事实库。公开 locator 继续是：

```json
{"version": "<edition.version>", "paragraph_id": "<hp_ID>"}
```

旧 edition 一旦发布即保持不变。追加或替换都生成新 edition；后续片段不会静默
改变旧版本的正文、状态、依据或定位。

## 输入片段

编排器只接受明确标记为 `published` 的片段。`publication_version` 是片段版本
作用域，`publication_id` 是发布记录作用域；两者在一次 edition 中都必须唯一。
片段顶层 `schema`/`version` 必须严格为
`chronicle.historical-publication`/`0.1`；不支持的片段协议会在编排前拒绝。
`coverage` 是审核用的非年份排序范围，采用同一 `scope` 下的半开区间
`[start, end)`，并可带首尾原文锚点。`year`/`period` 只作为历史资料字段，不是
排序键，也不能从相邻片段补造。

下面是一个最小、完整的片段形状（正文字符串和依据仍在片段中，edition 只保存
它们的引用）：

```json
{
  "schema": "chronicle.historical-publication",
  "version": "0.1",
  "publication_status": "published",
  "publication_version": "batch-a-r3",
  "publication_id": "pub-a",
  "coverage": {
    "scope": "chronicle-r3",
    "start": 0,
    "end": 1,
    "start_anchor": "source-0000",
    "end_anchor": "source-0000"
  },
  "phases": [{"id": "phase0", "label": "一段时期", "year": null, "period": null}],
  "paragraphs": [{
    "id": "p0",
    "ordinal": 0,
    "phase_id": "phase0",
    "segments": [{
      "text": "经过审核的正文。",
      "conclusion_ids": ["c0"],
      "event_id": null,
      "event_relation": null
    }],
    "entities": []
  }],
  "conclusions": [{
    "id": "c0",
    "phase_ids": ["phase0"],
    "event_id": null,
    "evidence": ["e0"]
  }],
  "evidence": [{"id": "e0", "publication_id": "pub-a", "quote": "原文依据。"}],
  "entry_points": [{
    "kind": "period",
    "label": "一段时期",
    "paragraph_id": "p0",
    "event_id": null,
    "reason": "这是已审核的精选入口。"
  }]
}
```

片段内的 `paragraph.ordinal` 必须是发布顺序 `0..n-1`；编排器不重新排序。段落
引用的 phase、conclusion、entity state 和 evidence 必须在同一个
`publication_version` 作用域内闭合。显式携带了其他 `fragment_version` 或其他
`publication_id` 的记录会以 `cross_fragment_reference` 拒绝。

## 接缝与边界审核

片段数组的输入顺序就是全局顺序。每个相邻 pair 都必须有一条边界审核：

```json
{
  "left_fragment_version": "batch-a-r3",
  "right_fragment_version": "batch-b-r3",
  "geometry": "contiguous",
  "status": "accepted",
  "review_basis": [
    {"fragment_version": "batch-a-r3", "paragraph_id": "p255"},
    {"fragment_version": "batch-b-r3", "paragraph_id": "p0"}
  ],
  "note": "审核确认两端在同一资料范围内连续。"
}
```

只有同一 `coverage.scope` 且左 `end ==` 右 `start` 的 `contiguous` 接缝可以
以 `accepted` 进入 edition。以下情况必须停留在待处理边界，不能自动拼成“流畅
历史”：

- `overlap`：两片段覆盖范围重叠；
- `gap`：范围之间有未覆盖区间；
- `inversion`：后片段的范围起点早于前片段；
- `different_scope`：两端不在同一可比较的范围；
- `coherent == false` 或 `seam_status` 为 `incoherent`/`pending`。

`inspect_boundaries()` 可以只返回这些几何结果供审核队列使用；
`compile_history_edition()` 遇到缺失、pending 或非 contiguous 接缝会抛出错误，
绝不会自行排序、去重或推测接缝意义。未知 `year`/`period` 原样保留为 `null`。

## 全局 ID 与 manifest

`hp_ID` 的派生输入严格为：

```text
sha256(canonical_json(["paragraph", fragment_version, source_paragraph_id]))[:24]
=> hp_<24 hex chars>
```

阶段、结论和事件使用同一个 canonical 规则并带各自 kind 前缀。因而三个片段都
可以有 `p0`、`phase0`、`c0`，但不会串线。manifest 的 `paragraphs`、`phases`、
`conclusions` 每项都带 `source` locator；`conclusions[].evidence[]` 也同时带
`fragment_version` 和 `evidence_id`。正文和状态不被复制到 manifest，后续读取层
按这些引用回到已发布片段。

编排结果的顶层形状如下；`version` 与 `manifest_sha256` 都是完整 manifest
payload（不含这两个 hash 字段）的 SHA-256，`content_sha256` 绑定有序片段内容
hash 和全部引用映射：

```json
{
  "schema": "chronicle.history-edition",
  "contract_version": "0.1",
  "version": "<sha256>",
  "fragments": [{
    "fragment_version": "batch-a-r3",
    "publication_id": "pub-a",
    "content_sha256": "<sha256>",
    "paragraph_count": 1,
    "coverage": {"scope": "chronicle-r3", "start": 0, "end": 1}
  }],
  "boundaries": [],
  "paragraphs": [{
    "paragraph_id": "hp_<24 hex chars>",
    "ordinal": 0,
    "source": {"fragment_version": "batch-a-r3", "paragraph_id": "p0"},
    "phase_id": "hphase_<24 hex chars>",
    "conclusion_ids": ["hcon_<24 hex chars>"],
    "content_ref": {"fragment_version": "batch-a-r3", "paragraph_id": "p0"}
  }],
  "phases": [{
    "phase_id": "hphase_<24 hex chars>",
    "source": {"fragment_version": "batch-a-r3", "phase_id": "phase0"},
    "year": null,
    "period": null
  }],
  "conclusions": [{
    "conclusion_id": "hcon_<24 hex chars>",
    "source": {"fragment_version": "batch-a-r3", "conclusion_id": "c0"},
    "phase_ids": ["hphase_<24 hex chars>"],
    "evidence": [{"fragment_version": "batch-a-r3", "evidence_id": "e0"}]
  }],
  "navigation": [],
  "paragraph_count": 1,
  "fragment_count": 1,
  "content_sha256": "<sha256>",
  "manifest_sha256": "<sha256>"
}
```

带 `<...>` 的片段是字段形状示意（需将同一占位符替换为实际派生值），不是可直接发布的 hash。可执行的统一样例
由 `contract_fixture(paragraphs_per_fragment=96, fragment_count=3)` 生成：它返回
三个各 96 段的片段（总计 288 段）、两条已接受接缝、每片段一个精选入口和
`edition`。因此 T10/T11 可以共享同一份输入，而不需要伪造第二套协议：

```python
from history_edition_contract import contract_fixture, validate_history_edition

fixture = contract_fixture(paragraphs_per_fragment=96, fragment_count=3)
edition = fixture["edition"]
assert edition["fragment_count"] == 3
assert edition["paragraph_count"] == 288
validate_history_edition(edition, fixture["fragments"])
```

传入片段快照时，`validate_history_edition()` 会按快照重新编排并逐项核对
manifest 的 source locator、派生 ID、边界和导航；即使调用方重新计算了 manifest
hash，指向不存在本地 ID 的篡改映射也会以 `source_mapping_mismatch` 拒绝。

`navigation` 只接受片段已有的精选入口或显式传入的少量入口，最多 12 项；不会
因为段落数或片段数增长而把所有事件/细节自动升级为入口。入口必须命中真实段落；
`kind == "event"` 还必须命中该段中 `current` 的同一事件。

## 持久化与读取接线（C3-T10）

`persistence/history_edition_store.py` 将上述纯合同接到 Chronicle 自有
PostgreSQL。`history_editions`、`history_edition_fragments` 和三个有序索引表
均为发布后不可变记录；`history_edition_latest` 是唯一可变的最新指针。
`history_edition_drafts` 只保存 Studio 的完整片段快照、基线和接缝审核引用，
不会成为事实或来源权威。

Studio 通过现有任务代理使用以下路径：

```text
GET  /api/v1/studio/jobs/history/editions/fragments
GET  /api/v1/studio/jobs/history/editions
POST /api/v1/studio/jobs/history/editions
GET  /api/v1/studio/jobs/history/editions/{draft_id}
POST /api/v1/studio/jobs/history/editions/{draft_id}/publish
POST /api/v1/studio/jobs/history/editions/{draft_id}/boundaries/{review_id}
```

最后一个路径仍写入现有 `ReviewItem(stage_gate)`；接缝必须带两侧段落锚点和
非空理由，只有 `resolved + accept` 才能进入 manifest。发布重新取得已有
全局发布 advisory lock，重查 edition 基线、片段 hash、接缝状态和（绑定任务
时的）未过期租约，最后才更新 latest 指针。

唯一公开主历史入口是 `/api/v1/public/history`（sidecar 的 `/v0/history`）：
省略 `version` 只读 latest 指针的元数据，带 `version` 则固定到该 edition；
段落和结论查询从有序索引按 ordinal/ID 读取，再回到对应片段，不加载整个
全局 manifest，也不调用模型。没有已发布 edition 时返回空态，未知版本、段落
或结论不会回退到最近批次。

## 错误码

纯合同异常为 `HistoryEditionError`，可读取 `.code`；它继承
`PersistenceError`，所以现有应用错误边界仍可统一处理。

| code | 拒绝条件 |
| --- | --- |
| `invalid_input` | 顶层、记录或字段形状不正确 |
| `unsupported_fragment_schema` | 片段 schema 不是 `chronicle.historical-publication` |
| `unsupported_fragment_version` | 片段 schema version 不是 `0.1` |
| `fragment_not_published` | 片段不是 `publication_status: published` |
| `duplicate_fragment` | 重复片段版本或发布记录 |
| `fragment_capacity_exceeded` | 任一片段超过 256 段 |
| `missing_reference` | 段落、阶段、结论或依据引用不存在 |
| `cross_fragment_reference` | 正文、状态、事件或依据越过片段作用域 |
| `local_order_changed` | ordinal 不再是原片段顺序，或入口倒置 |
| `mapping_incomplete` | 映射、范围、状态/依据闭合不完整 |
| `anchor_out_of_bounds` | 导航或边界锚点不在目标片段 |
| `entry_unreachable` | 精选入口不能到达实际段落/当前事件 |
| `boundary_review_missing` | 相邻片段没有审核接缝 |
| `boundary_review_required` | 重叠、缺口、倒置或不连贯仍待处理 |
| `boundary_review_invalid` | 审核 pair、几何或依据不匹配 |
| `manifest_hash_mismatch` | 不可变 manifest 或片段内容发生 hash 漂移 |
| `source_mapping_mismatch` | manifest 映射与传入片段快照不一致 |
| `baseline_changed` | append/replace 的并发基线 hash 已变化 |
| `replacement_range_invalid` | 替换没有以明确片段版本给出准确范围 |
| `replacement_version_reused` | 新片段复用了旧版本，可能静默改写历史 |

统一 fixture 的 `negative_inputs` 覆盖未发布、重复片段和越界入口；测试另覆盖
丢失引用、局部顺序变化、重叠/倒置/不连贯边界和跨片段状态/依据。

## 追加、替换与并发基线

```python
compile_history_edition(
    fragments,
    boundary_reviews=reviews,
    navigation=curated_entries,
)
append_history_edition(
    previous_edition,
    complete_post_append_snapshot,
    baseline_manifest_sha256=previous_edition["manifest_sha256"],
    boundary_reviews=reviews,
    navigation=curated_entries,
)
replace_history_edition(
    previous_edition,
    complete_post_replace_snapshot,
    replacement_range={
        "start_fragment_version": "batch-b-r3",
        "end_fragment_version": "batch-c-r3",
    },
    baseline_manifest_sha256=previous_edition["manifest_sha256"],
    boundary_reviews=reviews,
    navigation=curated_entries,
)
```

追加和替换都要求调用方带着读取到的完整片段快照进入纯函数：

- append 必须逐字保留旧片段引用，并在末尾新增至少一个全新版本；
- replace 的 range 以旧片段版本为首尾、包含两端，prefix/suffix 必须不变；不能
  传只有年份的范围，也不能复用被替换的片段版本；
- `baseline_manifest_sha256` 不等于当前 manifest 时返回 `baseline_changed`，
  不生成候选版本；
- 两者都生成带 `lineage.operation` 和 `lineage.parent_version` 的新 manifest，
  旧 edition 不被修改，即使新片段正文、状态或依据发生变化也只影响新版本。

函数和 fixture 均无数据库、网络、模型或系统时间依赖；后续持久化层负责把已经
通过本合同的 manifest 与现有发布锁/租约、原子可见性接线。
