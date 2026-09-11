// C2-R2-T02 harness suite 的基础场景注册（仅测试使用，不进生产构建）。
// 组件作者按同一接口在自己的 cases/<suite>/scene.tsx 里新增 ReadingScene。

import { BaseReadingWindow } from "./BaseReadingWindow";
import type { ReadingScene } from "../types";

const scenes: ReadingScene[] = [
  {
    name: "base-reading-window",
    suite: "harness",
    label: "基础阅读窗口、时间轴分组与受控响应（失败/迟到/空白）",
    synthetic: true,
    render: () => <BaseReadingWindow />,
  },
];

export default scenes;
