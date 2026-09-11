# 阅读组件 fixture 场景注册约定（C2-R2-T02）

本目录只被 `tests/fixtures/reading/main.tsx` 通过受控 glob
`./cases/*/scene.tsx` 发现；组件任务（T10–T14）只新增自己的
`cases/<suite>/scene.tsx` 与 `tests/reading-browser/<suite>.mjs`，
不改 `main.tsx`、`types.ts` 或他人的 suite 目录。

## scene.tsx 契约

```tsx
import type { ReadingScene } from "../types";

const scenes: ReadingScene[] = [
  {
    name: "unique-within-suite",
    suite: "content", // content | axis | position | events | context
    label: "中文场景说明",
    synthetic: true, // 人造 fixture 必须显式标记
    render: (params) => <MyFixture params={params} />,
  },
];

export default scenes; // 也可默认导出单个 ReadingScene
```

约束：

- `suite` 必须是 `harness|content|axis|position|events|context` 之一；
  `harness` 由 T02 基座拥有，组件任务只写自己的组件 suite。
- `name` 在 suite 内唯一；URL 为 `?case=<suite>/<name>`。
- `synthetic` 人造场景必须为 `true`，不得冒充真实史料或真实模型输出。
- 只演示 published DTO 形状（见 `../types.ts`）与受控响应（成功/失败/迟到/空白）；
  不接生产 App/路由，不写 `apps/chronicle/web/dist`，不新增 package/lock。

## 组件 suite 的 browser spec

`tests/reading-browser/<suite>.mjs` 导出：

```js
export async function run(ctx) {
  ctx.check("场景已渲染", true); // 失败即抛错
  const page = await ctx.openScene("my-scene");
  ctx.info("note", "evidence");
  await ctx.screenshot(page, "my-scene");
}
```

主 harness 会先确认 `cases/<suite>/scene.tsx` 已注册场景，再调用该 spec；
缺少 spec 记为 `suite_not_implemented`，缺少场景记为 `suite_no_scenes`，
两者都显式失败。`--suite all` 只有五类组件 suite 均存在且通过才成功。
