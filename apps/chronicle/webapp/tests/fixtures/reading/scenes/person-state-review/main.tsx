// C2-R3-T12 章阶段依据审核组件 fixture 入口（仅测试使用，不进生产构建）。
//
// 由 Vite 直接提供 `tests/fixtures/reading/scenes/person-state-review/index.html`。
// 场景只操作正式 PersonStateReviewPanel；无路由、无 sessionStorage、无 HTTP。

import { createRoot } from "react-dom/client";
import ReviewScene from "./ReviewScene";

const TASK = "C2-R3-T12";

(window as unknown as { __PERSON_STATE_REVIEW_HARNESS__: unknown }).__PERSON_STATE_REVIEW_HARNESS__ = {
  fixture: "person-state-review",
  builtFor: TASK,
  synthetic: true,
};

const root = createRoot(document.getElementById("root")!);
root.render(<ReviewScene />);
