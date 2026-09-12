// C2-R3-T11 组件场景入口（仅测试使用，不接生产构建）。
//
// 由 Vite 直接提供本目录的 index.html：`?case=reading`（完整阅读页骨架）与
// `?case=slot`（ReadingContextPanel 阶段 slot 注入）。未知场景显式失败。

import { createRoot } from "react-dom/client";
import PersonStatesScene from "./PersonStatesScene";

const SCENE_NAMES = ["reading", "slot"] as const;
type SceneName = (typeof SCENE_NAMES)[number];

const params = new URLSearchParams(window.location.search);
const requested = params.get("case") ?? "reading";
const root = createRoot(document.getElementById("root")!);

if ((SCENE_NAMES as readonly string[]).includes(requested)) {
  root.render(<PersonStatesScene mode={requested as SceneName} />);
} else {
  root.render(<main data-test="person-state-scene-missing">没有该场景：{requested}（显式失败，不静默回退）</main>);
}
