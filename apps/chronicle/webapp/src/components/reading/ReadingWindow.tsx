// C2-R2-T10 连续正文窗口：页合并/去重、有界渲染窗口、占位高度、固定单位与
// 加载失败/显式加载入口。
//
// 组件不拥有 active unit、路由或历史；通过 props 接收已加载 pages 与 active，
// 通过 T01 的 ReadingWindowCallbacks 请求翻页/重试，并把 DOM ready 与测量结果
// 回传给 T12 controller。正在聚焦/选择/展开引用的 unit 会被固定，不因窗口回收
// 而从 DOM 消失。

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FocusEvent as ReactFocusEvent,
} from "react";
import type { ChapterSourceClient } from "../ChapterSourceReference";
import {
  readingUnitText,
  type ReadingDirection,
  type ReadingUnit,
  type ReadingWindowCallbacks,
  type StreamPage,
} from "../../lib/reading-types";
import {
  applyMeasuredHeight,
  mergeReadingUnitPages,
  planReadingWindow,
  readingChapterHeadings,
  type ReadingWindowLimits,
} from "../../lib/reading-window";
import ReadingContent, {
  type ReadingEventRenderer,
  type ReadingSourceRenderer,
} from "./ReadingContent";

// 浏览器用 layout effect 立即测量；SSR（node 单测）退回 useEffect 以消除警告。
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export interface ReadingWindowError {
  readonly message: string;
  readonly direction?: ReadingDirection | null;
  readonly unitId?: string | null;
}

export interface ReadingWindowProps {
  /** 已加载的正文页（顺序不限）；窗口负责去重与排序。 */
  readonly pages: readonly StreamPage[];
  readonly activeUnitId?: string | null;
  /** publication-owned 章标题映射；缺失时回退 chapter_id。 */
  readonly chapterTitles?: Readonly<Record<string, string | null>>;
  readonly pinnedUnitIds?: readonly string[];
  readonly loadingDirection?: ReadingDirection | null;
  readonly error?: ReadingWindowError | null;
  readonly callbacks?: Partial<ReadingWindowCallbacks>;
  readonly limits?: Partial<ReadingWindowLimits>;
  readonly sourceClient?: ChapterSourceClient;
  readonly renderEvent?: ReadingEventRenderer;
  readonly renderSource?: ReadingSourceRenderer;
  /** 目标 unit 的 DOM 装载完成（供 controller locate/聚焦）。 */
  readonly onUnitReady?: (unitId: string, element: HTMLElement) => void;
  /** 测得目标 unit 高度（供 controller 恢复滚动位置）。 */
  readonly onUnitMeasured?: (unitId: string, height: number) => void;
  /** 固定单位集合变化时通知 controller。 */
  readonly onPinnedUnitIdsChange?: (unitIds: readonly string[]) => void;
}

interface MountedUnitProps {
  unit: ReadingUnit;
  active: boolean;
  pinned: boolean;
  chapterTitle: string | null;
  showChapterHeading: boolean;
  expandedAnchorId: string | null;
  sourceClient?: ChapterSourceClient;
  renderEvent?: ReadingEventRenderer;
  renderSource?: ReadingSourceRenderer;
  onToggleSource: (unitId: string, anchorId: string | null) => void;
  onReady: (unitId: string, element: HTMLElement) => void;
  onMeasured: (unitId: string, height: number) => void;
}

function MountedUnit({
  unit,
  active,
  pinned,
  chapterTitle,
  showChapterHeading,
  expandedAnchorId,
  sourceClient,
  renderEvent,
  renderSource,
  onToggleSource,
  onReady,
  onMeasured,
}: MountedUnitProps) {
  const ref = useRef<HTMLElement | null>(null);
  const readyRef = useRef(onReady);
  const measuredRef = useRef(onMeasured);
  readyRef.current = onReady;
  measuredRef.current = onMeasured;

  useIsomorphicLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    readyRef.current(unit.unit_id, element);
    const measure = () => measuredRef.current(unit.unit_id, element.getBoundingClientRect().height);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [unit.unit_id]);

  return (
    <article
      ref={ref}
      className="rcw-unit"
      data-test="reading-unit"
      data-unit-id={unit.unit_id}
      data-ordinal={unit.ordinal}
      data-chapter-id={unit.chapter_id}
      data-text={readingUnitText(unit)}
      data-active={active ? "true" : "false"}
      data-pinned={pinned ? "true" : "false"}
    >
      <ReadingContent
        unit={unit}
        chapterTitle={chapterTitle}
        showChapterHeading={showChapterHeading}
        expandedAnchorId={expandedAnchorId}
        sourceClient={sourceClient}
        renderEvent={renderEvent}
        renderSource={renderSource}
        onToggleSource={onToggleSource}
      />
    </article>
  );
}

function directionLabel(direction: ReadingDirection): string {
  return direction === "previous" ? "前文" : "后文";
}

/** 正文窗口；active unit、路由与历史由 T12 controller 拥有。 */
export default function ReadingWindow({
  pages,
  activeUnitId = null,
  chapterTitles,
  pinnedUnitIds: externalPinned,
  loadingDirection = null,
  error = null,
  callbacks,
  limits,
  sourceClient,
  renderEvent,
  renderSource,
  onUnitReady,
  onUnitMeasured,
  onPinnedUnitIdsChange,
}: ReadingWindowProps) {
  const [heights, setHeights] = useState<Readonly<Record<string, number>>>({});
  const [expandedSources, setExpandedSources] = useState<Record<string, string>>({});
  const [focusedUnitId, setFocusedUnitId] = useState<string | null>(null);
  const [selectionPinned, setSelectionPinned] = useState<readonly string[]>([]);

  const units = useMemo(() => mergeReadingUnitPages(pages), [pages]);
  const headings = useMemo(
    () => readingChapterHeadings(units, chapterTitles),
    [units, chapterTitles],
  );

  const pinnedUnitIds = useMemo(() => {
    const list: string[] = [];
    const push = (id: string | null | undefined) => {
      if (id && id.length > 0 && !list.includes(id)) list.push(id);
    };
    push(activeUnitId);
    for (const id of externalPinned ?? []) push(id);
    push(focusedUnitId);
    for (const id of selectionPinned) push(id);
    for (const id of Object.keys(expandedSources)) push(id);
    return list;
  }, [activeUnitId, externalPinned, focusedUnitId, selectionPinned, expandedSources]);

  const plan = useMemo(
    () =>
      planReadingWindow({
        units,
        activeUnitId,
        pinnedUnitIds,
        placeholderHeights: heights,
        limits,
      }),
    [units, activeUnitId, pinnedUnitIds, heights, limits],
  );

  const pinnedChangeRef = useRef(onPinnedUnitIdsChange);
  pinnedChangeRef.current = onPinnedUnitIdsChange;
  useEffect(() => {
    pinnedChangeRef.current?.(plan.pinnedUnitIds);
  }, [plan.pinnedUnitIds]);

  const measuredCallbackRef = useRef(onUnitMeasured);
  measuredCallbackRef.current = onUnitMeasured;

  const readyCallbackRef = useRef(onUnitReady);
  readyCallbackRef.current = onUnitReady;

  const handleMeasured = useCallback((unitId: string, height: number) => {
    setHeights((previous) => applyMeasuredHeight(previous, unitId, height));
    measuredCallbackRef.current?.(unitId, height);
  }, []);

  const handleReady = useCallback((unitId: string, element: HTMLElement) => {
    readyCallbackRef.current?.(unitId, element);
  }, []);

  const handleToggleSource = useCallback((unitId: string, anchorId: string | null) => {
    setExpandedSources((previous) => {
      const next = { ...previous };
      if (anchorId) next[unitId] = anchorId;
      else delete next[unitId];
      return next;
    });
  }, []);

  // 文本选择固定：selectionchange 时才扫描，不在每个 scroll 事件里做。
  useEffect(() => {
    const onSelectionChange = () => {
      const selection = typeof window === "undefined" ? null : window.getSelection();
      const next = new Set<string>();
      if (selection && !selection.isCollapsed && selection.rangeCount > 0) {
        for (const node of [selection.anchorNode, selection.focusNode]) {
          const element =
            node instanceof HTMLElement ? node : (node?.parentElement ?? null);
          const unitElement = element?.closest?.('[data-test="reading-unit"]') ?? null;
          const unitId = unitElement?.getAttribute("data-unit-id");
          if (unitId) next.add(unitId);
        }
      }
      const nextList = [...next];
      setSelectionPinned((previous) => {
        if (previous.length === nextList.length && previous.every((id, index) => id === nextList[index])) {
          return previous;
        }
        return nextList;
      });
    };
    document.addEventListener("selectionchange", onSelectionChange);
    return () => document.removeEventListener("selectionchange", onSelectionChange);
  }, []);

  const handleFocus = (event: ReactFocusEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null;
    const unitElement = target?.closest?.('[data-test="reading-unit"]') ?? null;
    setFocusedUnitId(unitElement?.getAttribute("data-unit-id") ?? null);
  };

  const handleBlur = (event: ReactFocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget as HTMLElement | null;
    if (next && event.currentTarget.contains(next)) return;
    setFocusedUnitId(null);
  };

  const mountedSet = useMemo(() => new Set(plan.mountedUnitIds), [plan.mountedUnitIds]);
  const placeholderByUnit = useMemo(() => {
    const map = new Map(plan.placeholders.map((placeholder) => [placeholder.unit_id, placeholder]));
    return map;
  }, [plan.placeholders]);

  const hasContent = units.length > 0;
  const showEmpty = !hasContent && !loadingDirection && !error;

  return (
    <div
      className="rcw-window"
      data-test="reading-window"
      data-mounted={plan.mountedUnitIds.length}
      data-auto-prefetch={plan.autoPrefetch ? "true" : "false"}
      onFocusCapture={handleFocus}
      onBlurCapture={handleBlur}
    >
      {plan.requiresExplicitLoad ? (
        <div className="rcw-paused" data-test="reading-paused" role="status">
          <p className="rcw-paused-text">
            已暂停自动预取：当前正文窗口已达上限，你正在阅读的段落仍保留。
          </p>
          <div className="rcw-manual-controls" data-test="reading-load-more">
            <button
              type="button"
              className="rcw-manual-button"
              data-test="reading-manual-previous"
              onClick={() => callbacks?.requestPage?.("previous")}
            >
              继续加载前文
            </button>
            <button
              type="button"
              className="rcw-manual-button"
              data-test="reading-manual-next"
              onClick={() => callbacks?.requestPage?.("next")}
            >
              继续加载后文
            </button>
          </div>
        </div>
      ) : null}

      {loadingDirection ? (
        <p className="rcw-loading" data-test="reading-loading" data-direction={loadingDirection}>
          正在加载{directionLabel(loadingDirection)}…
        </p>
      ) : null}

      {error ? (
        <div className="rcw-error" data-test="reading-load-error" role="alert">
          <p>正文{error.direction ? directionLabel(error.direction) : ""}加载失败：{error.message}</p>
          <p className="rcw-error-note">已读正文保留，不会清空。</p>
          <button
            type="button"
            className="rcw-retry-button"
            data-test="reading-retry"
            onClick={() => callbacks?.onRetry?.(error.unitId ?? activeUnitId ?? "")}
          >
            重试
          </button>
        </div>
      ) : null}

      {showEmpty ? (
        <p className="rcw-empty" data-test="reading-empty">
          这里还没有已发布的正文。
        </p>
      ) : null}

      <div className="rcw-units">
        {units.map((unit) => {
          if (!mountedSet.has(unit.unit_id)) {
            const placeholder = placeholderByUnit.get(unit.unit_id);
            const height = placeholder?.height ?? 0;
            return (
              <div
                key={unit.unit_id}
                className="rcw-placeholder"
                data-test="reading-unit-placeholder"
                data-unit-id={unit.unit_id}
                data-ordinal={unit.ordinal}
                data-height={height}
                data-estimated={placeholder?.estimated ? "true" : "false"}
                style={{ height: `${height}px` }}
                aria-hidden="true"
              />
            );
          }
          const heading = headings[unit.unit_id];
          return (
            <MountedUnit
              key={unit.unit_id}
              unit={unit}
              active={unit.unit_id === activeUnitId}
              pinned={plan.pinnedUnitIds.includes(unit.unit_id)}
              chapterTitle={heading?.chapter_title ?? null}
              showChapterHeading={Boolean(heading)}
              expandedAnchorId={expandedSources[unit.unit_id] ?? null}
              sourceClient={sourceClient}
              renderEvent={renderEvent}
              renderSource={renderSource}
              onToggleSource={handleToggleSource}
              onReady={handleReady}
              onMeasured={handleMeasured}
            />
          );
        })}
      </div>
    </div>
  );
}
