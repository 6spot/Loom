// C2-R2-T10 content suite 场景注册（仅测试使用，不进生产构建）。
//
// 组件作者按 T02 约定在 cases/<suite>/scene.tsx 暴露 ReadingScene；样式只在
// fixture 页面导入，不写生产 dist、不改 App 或全局 CSS。chapter-reader.css 是
// 第一轮 ChapterSourceReference 的既有样式，这里只为在 fixture 中忠实复用。

import "../../../../../src/styles/chapter-reader.css";
import "../../../../../src/styles/reading-content.css";
import { ControlledContentWindow } from "./ControlledContentWindow";
import type { ReadingScene } from "../types";

const scenes: ReadingScene[] = [
  {
    name: "content-window",
    suite: "content",
    label: "连续正文窗口：跨章顺序、双向加载、有界回收、固定单位与按需原文",
    synthetic: true,
    render: () => <ControlledContentWindow />,
  },
];

export default scenes;
