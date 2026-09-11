---
task: C2-R3-T12
issue: 630
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T01, C2-R3-D02, C2-R1-T11, C2-R1-T12]
---

# 按章阶段依据审核表单与连续操作组件

## 范围与交接

[Issue #630](https://github.com/6spot/Loom/issues/630) 对应本任务；具体实施步骤、文件归属和验收要求保留在下文。让操作者读懂人物变化及时间依据，集中核对与逐项例外都能在长页面连续完成。

- 输入：D02审核设计、T01 frozen review/decision DTO与browser runner；R1 ReviewEvidencePanel和连续审核约定。
- 交付：PersonStateReviewPanel、显示helper与自己的scene/spec；props为review/draft/onDraftChange/onSubmit/onSkip/onReturn，不挂接Studio页面。
- 前置：[C2-R3-T01](https://github.com/6spot/Loom/issues/619)、[C2-R3-D02](https://github.com/6spot/Loom/issues/618)、[C2-R1-T11](https://github.com/6spot/Loom/issues/561)、[C2-R1-T12](https://github.com/6spot/Loom/issues/562)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §5、8 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/webapp/src/components/studio/PersonStateReviewPanel.tsx（新）`
- `apps/chronicle/webapp/src/lib/person-state-review-display.ts（新）`
- `apps/chronicle/webapp/src/styles/person-state-review.css（新）`
- `apps/chronicle/webapp/tests/person-state-review-display.test.ts（新）`
- `apps/chronicle/webapp/tests/fixtures/reading/scenes/person-state-review/**（新）`
- `apps/chronicle/webapp/tests/reading-browser/person-state-review.mjs（新）`

可与 T11/后端并行。复用只读来源组件，现有review-session、studio-api、StudioReviewPage/Detail均由T13/T10按序接手。

## 实施步骤

1. 每章包按人物呈现事实/变化链，共用阶段依据单列；保留原文归属及批量/例外实际覆盖数量。
2. 提供supported/uncertain/disputed/rejected及按candidate_id的例外，呈现当前身份/此前记载/结束的预测效果与依据。
3. 默认/例外draft使用明确typed数据；切换plan/item时不沿用旧值，来源分页失败不影响输入，限定语不藏在技术详情。
4. 表单接受外部save/skip/next/return回调，固定操作区；提交中禁重复，400/409/503/未知结果保留draft并说明核对服务端状态。
5. 用真实浏览器验证长章页底连续处理、所有候选可达、例外不串条目、窗口/整章原文、窄屏与键盘。

## 验收

- [ ] 全部候选及共有时间依据可查看；批量确认不意味着人物合并或永久在任。
- [ ] 例外按精确候选键提交，清楚区别未审/暂时跳过与明确提交不明确。
- [ ] 长页底可保存并下一项，失败保留草稿和已读来源，不强制滚回顶部。
- [ ] 独立组件suite覆盖切项/迟到/409/窄屏/键盘，不抢写共享session或页面入口。

## 验证要求

```bash
npm --prefix apps/chronicle/webapp test -- tests/person-state-review-display.test.ts
node apps/chronicle/webapp/scripts/reading-component-smoke.mjs --base-url http://127.0.0.1:5173 --suite person-state-review --output /tmp/chronicle-r3-review-components
```

保存成功/失败通过外部callback模拟以验证组件；实际HTTP决定与持久化由T10/T14整链验证。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
