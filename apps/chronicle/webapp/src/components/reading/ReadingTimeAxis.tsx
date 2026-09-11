// C2-R2-T11 按叙事时间分组的侧边轴与窄屏时间入口。
//
// 数据含义、分页与定位契约见 continuous-reading.md §3/§5/§6；布局与交互见
// reading-experience.md §1/§2/§4。本组件只消费服务端编译好的 TimeGroups：
// - 不按年份重新归组，不生成补齐年月，不把史料历月当公历月；
// - 点击区段只发出精确 locator（stream + catalog + unit），不传年份；
// - 轴体反映叙事顺序，倒叙只标记不重排；
// - 桌面 sticky 轴 / 平板窄轴 / 手机可展开列表由 reading-axis.css 控制。
//
// 尚未挂接 App：T15 负责统一接入阅读页面与生产构建。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReadingLocator, TimeGroup } from "../../lib/reading-types";
import {
  axisBasisLabel,
  axisPeriodLabel,
  axisYearLabel,
  buildAxisModel,
} from "../../lib/reading-time-display";
import "../../styles/reading-axis.css";

export interface ReadingTimeAxisProps {
  /** 服务端已编译、按阅读顺序排列的时间区段；分页时由父级追加。 */
  readonly groups: readonly TimeGroup[];
  /** 当前区段 group_id；没有 active 时传 null。 */
  readonly activeGroup: string | null;
  /** 点击区段发出精确 locator。 */
  readonly onNavigate: (locator: ReadingLocator) => void;
  /** 有界分组分页：请求追加下一页轴区段。 */
  readonly onLoadGroups: () => void;
  readonly hasMoreGroups?: boolean;
  readonly loadingGroups?: boolean;
  readonly label?: string;
}

export default function ReadingTimeAxis({
  groups,
  activeGroup,
  onNavigate,
  onLoadGroups,
  hasMoreGroups = false,
  loadingGroups = false,
  label = "阅读时间轴",
}: ReadingTimeAxisProps) {
  const model = useMemo(() => buildAxisModel(groups, activeGroup), [groups, activeGroup]);
  const [mobileOpen, setMobileOpen] = useState(false);

  const listRef = useRef<HTMLOListElement | null>(null);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    if (model.activeIndex < 0) return;
    const node = buttonRefs.current[model.activeIndex];
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ block: "nearest" });
    }
  }, [model.activeIndex]);

  const focusButtonAt = useCallback(
    (position: number) => {
      const buttons = buttonRefs.current.filter((node): node is HTMLButtonElement => node !== null);
      if (buttons.length === 0) return;
      const clamped = Math.max(0, Math.min(buttons.length - 1, position));
      buttons[clamped]?.focus();
    },
    [],
  );

  const handleListKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLOListElement>) => {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "Home" && event.key !== "End") {
        return;
      }
      const buttons = buttonRefs.current.filter((node): node is HTMLButtonElement => node !== null);
      const current = buttons.findIndex((node) => node === document.activeElement);
      event.preventDefault();
      if (event.key === "Home") focusButtonAt(0);
      else if (event.key === "End") focusButtonAt(buttons.length - 1);
      else focusButtonAt(current + (event.key === "ArrowDown" ? 1 : -1));
    },
    [focusButtonAt],
  );

  const handleAxisKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLElement>) => {
      if (event.key !== "Escape") return;
      if (mobileOpen) {
        setMobileOpen(false);
        toggleRef.current?.focus();
      }
    },
    [mobileOpen],
  );

  const navigateTo = useCallback(
    (group: TimeGroup) => {
      onNavigate(group.first_locator);
      if (mobileOpen) setMobileOpen(false);
    },
    [mobileOpen, onNavigate],
  );

  return (
    <nav
      className="rax-axis"
      data-test="reading-time-axis"
      data-active-group={activeGroup ?? ""}
      aria-label={label}
      onKeyDown={handleAxisKeyDown}
    >
      <button
        type="button"
        ref={toggleRef}
        className="rax-toggle"
        data-test="reading-axis-toggle"
        aria-expanded={mobileOpen}
        aria-controls="reading-axis-list"
        onClick={() => setMobileOpen((open) => !open)}
      >
        {mobileOpen ? "收起时间轴" : "时间轴"}
      </button>

      <div
        className="rax-panel"
        data-test="reading-axis-panel"
        data-open={mobileOpen}
        id="reading-axis-list"
      >
        {groups.length === 0 ? (
          <p className="rax-empty" data-test="reading-axis-empty">
            暂无时间区段
          </p>
        ) : (
          <ol className="rax-list" ref={listRef} onKeyDown={handleListKeyDown}>
            {model.entries.map((entry) => {
              const yearLabel = axisYearLabel(entry.group);
              const basisLabel = axisBasisLabel(entry.basis);
              return (
                <li
                  className="rax-item"
                  key={entry.group.group_id}
                  data-group-id={entry.group.group_id}
                  data-continuation={entry.isContinuation}
                >
                  {entry.showYearHeader && yearLabel ? (
                    <div
                      className="rax-year"
                      data-test="reading-axis-year"
                      data-year-key={entry.group.year_key ?? ""}
                    >
                      {yearLabel}
                    </div>
                  ) : null}
                  <button
                    type="button"
                    ref={(node) => {
                      buttonRefs.current[entry.index] = node;
                    }}
                    className="rax-group"
                    data-test="reading-axis-group"
                    data-group-id={entry.group.group_id}
                    data-precision={entry.group.precision}
                    data-basis={entry.basis}
                    data-active={entry.isActive}
                    data-retrospective={entry.isRetrospective}
                    data-continuation={entry.isContinuation}
                    data-unknown={entry.isUnknown}
                    aria-current={entry.isActive ? "true" : undefined}
                    aria-label={entry.ariaLabel}
                    onClick={() => navigateTo(entry.group)}
                  >
                    {entry.showPeriodHeader ? (
                      <span className="rax-period" data-test="reading-axis-period">
                        {axisPeriodLabel(entry.group)}
                      </span>
                    ) : (
                      <span className="rax-period-continued" data-test="reading-axis-continued">
                        延续
                      </span>
                    )}
                    <span className="rax-meta">
                      {basisLabel ? (
                        <span className="rax-badge" data-test="reading-axis-basis">
                          {basisLabel}
                        </span>
                      ) : null}
                      <span className="rax-badge" data-test="reading-axis-precision">
                        {entry.precisionLabel}
                      </span>
                      {entry.isRetrospective ? (
                        <span className="rax-badge rax-badge-retro" data-test="reading-axis-retro">
                          倒叙
                        </span>
                      ) : null}
                      <span className="rax-count" data-test="reading-axis-count">
                        {entry.group.unit_count} 段
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        )}

        {hasMoreGroups ? (
          <button
            type="button"
            className="rax-load-more"
            data-test="reading-axis-load-more"
            onClick={onLoadGroups}
            disabled={loadingGroups}
          >
            加载更多区段
          </button>
        ) : null}
        {loadingGroups ? (
          <p className="rax-loading" data-test="reading-axis-loading">
            载入中…
          </p>
        ) : null}
      </div>
    </nav>
  );
}
