// C2-R2-T11 axis suite 场景注册（仅测试使用，不进生产构建）。
//
// 主 harness 通过 `cases/*/scene.tsx` 发现本文件；本任务只新增 axis suite，
// 不改 main.tsx / cases/types.ts / 基座 suite。

import { AxisScene } from "./AxisScene";
import {
  buildManyGroups,
  CALENDAR_GROUPS,
  HIERARCHY_GROUPS,
  PAGINATION_PAGE1,
  PAGINATION_PAGE2,
  RETRO_GROUPS,
} from "./fixtures";
import type { ReadingScene } from "../types";

const scenes: ReadingScene[] = [
  {
    name: "axis-hierarchy",
    suite: "axis",
    label: "年/月层级：同年共享年标题、换月、换年与未知区段",
    synthetic: true,
    render: () => <AxisScene groups={HIERARCHY_GROUPS} active="tg_axis_h1" heading="时间轴：年/月层级" />,
  },
  {
    name: "axis-calendars",
    suite: "axis",
    label: "历法与精度：来源历月、公历、近似、年段、多源分歧、闰月 opaque",
    synthetic: true,
    render: () => <AxisScene groups={CALENDAR_GROUPS} heading="时间轴：历法与精度标签" />,
  },
  {
    name: "axis-retrograde",
    suite: "axis",
    label: "倒叙：已知年份回退只标记不重排，未知不改最大年",
    synthetic: true,
    render: () => <AxisScene groups={RETRO_GROUPS} heading="时间轴：倒叙标记" />,
  },
  {
    name: "axis-pagination",
    suite: "axis",
    label: "有界分组分页：跨页同月延续与换年标题",
    synthetic: true,
    render: () => <AxisScene groups={PAGINATION_PAGE1} moreGroups={PAGINATION_PAGE2} heading="时间轴：分页延续" />,
  },
  {
    name: "axis-many",
    suite: "axis",
    label: "1,000 个区段的长轴渲染与窄屏溢出",
    synthetic: true,
    render: () => <AxisScene groups={buildManyGroups(1000)} heading="时间轴：1,000 区段" />,
  },
];

export default scenes;
