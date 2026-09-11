// C2-R2-T11 axis suite fixture 场景外壳（仅测试使用，不进生产构建）。
//
// 只负责把生产组件 ReadingTimeAxis 挂到一个合成 published-DTO 数据源上，记录
// 点击发出的 locator 与分页请求次数，供浏览器 spec 断言；它不冒充真实后端。

import { useState } from "react";
import ReadingTimeAxis from "../../../../../src/components/reading/ReadingTimeAxis";
import type { ReadingLocator, TimeGroup } from "../../../../../src/lib/reading-types";

export interface AxisSceneProps {
  readonly groups: readonly TimeGroup[];
  readonly active?: string | null;
  readonly moreGroups?: readonly TimeGroup[];
  readonly heading?: string;
}

export function AxisScene({ groups: initialGroups, active = null, moreGroups, heading }: AxisSceneProps) {
  const [groups, setGroups] = useState<readonly TimeGroup[]>(initialGroups);
  const [activeGroup, setActiveGroup] = useState<string | null>(active);
  const [lastNav, setLastNav] = useState<ReadingLocator | null>(null);
  const [loadCount, setLoadCount] = useState(0);
  const hasMoreGroups = moreGroups !== undefined && loadCount === 0;

  return (
    <main data-test="axis-fixture" data-synthetic="true">
      <p data-test="reading-synthetic-note">
        合成 fixture：只演示 published DTO 形状与轴交互，非真实后端、非真实模型输出，也不冒充史料。
      </p>
      {heading ? <h1 data-test="axis-fixture-heading">{heading}</h1> : null}
      <div
        className="axis-fixture-layout"
        style={{
          display: "grid",
          gap: "1.5rem",
          gridTemplateColumns: "minmax(0, 11rem) minmax(0, 1fr)",
          alignItems: "start",
          marginTop: "1rem",
        }}
      >
        <ReadingTimeAxis
          groups={groups}
          activeGroup={activeGroup}
          hasMoreGroups={hasMoreGroups}
          onLoadGroups={() => {
            if (moreGroups) setGroups((current) => [...current, ...moreGroups]);
            setLoadCount((count) => count + 1);
          }}
          onNavigate={(locator) => {
            setLastNav(locator);
            const hit = groups.find((candidate) => candidate.first_locator.unit_id === locator.unit_id);
            if (hit) setActiveGroup(hit.group_id);
          }}
        />
        <article
          data-test="axis-fixture-body"
          style={{ minWidth: 0, maxWidth: "42rem", lineHeight: 1.85 }}
        >
          <p>正文占位段落：用于观察侧边轴在桌面/平板/手机上是否挤压正文。</p>
          <p>正文占位段落：轴只反映叙事顺序，不按年份数字重排文字。</p>
        </article>
      </div>
      <output
        data-test="reading-axis-last-nav"
        data-stream={lastNav?.stream_id ?? ""}
        data-catalog={lastNav?.catalog_sha ?? ""}
        data-unit={lastNav?.unit_id ?? ""}
      />
      <span data-test="reading-axis-load-count">{loadCount}</span>
    </main>
  );
}
