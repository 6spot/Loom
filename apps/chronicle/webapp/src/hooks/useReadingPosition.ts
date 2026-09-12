// Chronicle 第二轮阅读定位控制器（C2-R2-T12）。
//
// 单一 controller 维护 {stream, catalog, active_unit, narrative_time, navigation_state}
// （reading-experience.md §4/§6）。正文窗口通过注入的 callbacks 交接，不直接依赖
// T10 实现文件；本 hook 负责 active unit、路由与恢复，事件/轴组件只能请求 navigation。
//
// 恢复语义：先校验 snapshot/stream/unit，调用 locate，等待目标真实 DOM，再恢复
// unit 内相对位置与焦点；旧请求按序号忽略，用户滚动可打断；不使用旧 scrollY、
// 不按年份猜位置。存储失败或 token 失效时退回 URL 定位/“进入相关正文”，绝不外部跳转。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  ContextEntityView,
  NarrativeTime,
  ReadingLocator,
  ReadingNavigationAction,
} from "../lib/reading-types";
import { isReadingLocator } from "../lib/reading-types";
import {
  buildReadingUrl,
  createFrameScheduler,
  nextNavigationState,
  parseReadingUrl,
  referenceLineFor,
  relativeOffsetWithin,
  readingIssue,
  selectActiveUnit,
  type FrameScheduler,
  type MeasuredUnit,
  type ReadingNavigationState,
  type ReadingUrlIssue,
  type ReadingUrlParse,
} from "../lib/reading-location";
import {
  ReadingHistoryStore,
  ReadingStorage,
  type RandomBytes,
  type StorageLike,
} from "../lib/reading-history";

let historySequence = 0;

export interface ReadingUnitSnapshot {
  readonly unitId: string;
  readonly ordinal: number;
  readonly narrativeTime: NarrativeTime;
  readonly contextEntities: readonly ContextEntityView[];
}

export interface ReadingLocateResult {
  readonly locator: ReadingLocator;
  readonly unitIds: readonly string[];
}

/** URL 策略：生产实现使用固定 `/read/...` 路由；测试/适配层可注入 query 映射。 */
export interface ReadingUrlStrategy {
  parse(url: string): ReadingUrlParse;
  build(locator: ReadingLocator): string;
  /** Adapter validates its own scope/version/item IDs; source defaults stay strict. */
  validate?: (value: unknown) => value is ReadingLocator;
  storagePrefix?: string;
}

export const DEFAULT_READING_URL_STRATEGY: ReadingUrlStrategy = {
  parse: parseReadingUrl,
  build: buildReadingUrl,
};

export interface ReadingPositionOptions {
  /** active unit 的叙事时间/上下文来源，禁止模型/组件各自维护第二份状态。 */
  readonly getUnit: (unitId: string) => ReadingUnitSnapshot | null;
  /** 精确 locate：返回目标 unit 所在页的 unit ids，或 null 表示失效。 */
  readonly locate: (locator: ReadingLocator, signal?: AbortSignal) => Promise<ReadingLocateResult | null>;
  /** 窗口加载：确保目标页已进入内容窗口（可选）。 */
  readonly loadWindow?: (locator: ReadingLocator) => void | Promise<void>;
  /** 自定义滚动到 unit 内相对位置；缺省用 DOM 元素测量。 */
  readonly scrollToUnit?: (unitId: string, relativeOffset: number) => void;
  /** URL 缺 `at` 时解析该 stream 首个 unit；缺失则显式报错。 */
  readonly resolveStart?: (route: {
    readonly stream_id: string;
    readonly catalog_sha: string;
  }) => Promise<ReadingLocator | null>;
  readonly onActiveUnitChange?: (unit: ReadingUnitSnapshot | null) => void;
  readonly storage?: StorageLike | null;
  readonly randomBytes?: RandomBytes;
  readonly urlStrategy?: ReadingUrlStrategy;
  readonly unitSelector?: string;
  readonly unitIdAttribute?: string;
  readonly ordinalAttribute?: string;
  readonly headerHeight?: number;
  readonly referenceRatio?: number;
  readonly settleDelayMs?: number;
  readonly restoreFrameBudget?: number;
  /** Window reports layout changes; this controller preserves the reading point. */
  readonly preserveLayoutPosition?: boolean;
  /** Current contiguous window's existing HTTP page flags, used only at a scroll boundary. */
  readonly getWindowEdges?: (unitId: string) => { readonly hasPrevious: boolean; readonly hasNext: boolean };
}

export interface ReadingPositionControllerState {
  readonly stream: string | null;
  readonly catalog: string | null;
  readonly locator: ReadingLocator | null;
  readonly activeUnitId: string | null;
  readonly activeOrdinal: number | null;
  readonly activeUnit: ReadingUnitSnapshot | null;
  readonly navigationState: ReadingNavigationState;
  readonly issue: ReadingUrlIssue | null;
}

export interface ReadingPositionController extends ReadingPositionControllerState {
  readonly narrativeTime: NarrativeTime | null;
  readonly contextEntities: readonly ContextEntityView[];
  readonly storageAvailable: boolean;
  navigate(action: ReadingNavigationAction): void;
  restoreLocator(
    locator: ReadingLocator,
    options?: { readonly push?: boolean; readonly relativeOffset?: number; readonly focusId?: string | null },
  ): void;
  restoreFromUrl(): void;
  rememberReturnTarget(): { token: string; locator: ReadingLocator; persisted: boolean } | null;
  restoreReturnToken(token: string): ReadingLocator | null;
  previewEvent(eventId: string): void;
  notifyLayoutChange(unitId?: string): void;
}

interface RestoreDetail {
  readonly relativeOffset: number;
  readonly focusId: string | null;
  readonly sourceExpanded: boolean;
  readonly historyKey?: string;
  readonly push: boolean;
}

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const SCROLL_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "PageUp",
  "PageDown",
  "Home",
  "End",
  " ",
  "Spacebar",
]);

function defaultSessionStorage(): StorageLike | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

function prefersReducedMotion(): boolean {
  try {
    return typeof window !== "undefined" && window.matchMedia(REDUCED_MOTION_QUERY).matches;
  } catch {
    return false;
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function useReadingPosition(options: ReadingPositionOptions): ReadingPositionController {
  const strategy = options.urlStrategy ?? DEFAULT_READING_URL_STRATEGY;
  const unitSelector = options.unitSelector ?? "[data-reading-unit]";
  const unitIdAttribute = options.unitIdAttribute ?? "data-unit-id";
  const ordinalAttribute = options.ordinalAttribute ?? "data-ordinal";
  const headerHeight = options.headerHeight ?? 0;
  const referenceRatio = options.referenceRatio ?? 0.3;
  const settleDelayMs = options.settleDelayMs ?? 250;
  const restoreFrameBudget = options.restoreFrameBudget ?? 120;
  const randomBytes = options.randomBytes;

  const storageAdapter = useMemo(
    () =>
      new ReadingStorage(
        options.storage === undefined ? defaultSessionStorage() : options.storage,
        strategy.storagePrefix,
      ),
    [options.storage, strategy.storagePrefix],
  );
  const store = useMemo(
    () => new ReadingHistoryStore(storageAdapter, { randomBytes, validateLocator: strategy.validate }),
    [storageAdapter, randomBytes, strategy.validate],
  );
  const storageAvailable = useMemo(() => storageAdapter.available(), [storageAdapter]);

  const [state, setState] = useState<ReadingPositionControllerState>({
    stream: null,
    catalog: null,
    locator: null,
    activeUnitId: null,
    activeOrdinal: null,
    activeUnit: null,
    navigationState: "idle",
    issue: null,
  });

  const stateRef = useRef(state);
  const optionsRef = useRef(options);
  const storeRef = useRef(store);
  const strategyRef = useRef(strategy);
  const mountedRef = useRef(false);
  const requestSeqRef = useRef(0);
  const operationAbortRef = useRef<AbortController | null>(null);
  const historyKeyRef = useRef("");
  const activeRef = useRef<{ unitId: string; ordinal: number } | null>(null);
  // 导航状态用 ref 同步跟踪，避免 rAF/滚动回调在 React 重渲染前读到过期的 state。
  const navStateRef = useRef<ReadingNavigationState>("idle");
  const settleTimerRef = useRef<number | null>(null);
  const schedulerRef = useRef<FrameScheduler | null>(null);
  const layoutAnchorRef = useRef<{
    unitId: string;
    offset: number;
    documentPoint: number;
    referenceLine: number;
    pending?: { relativeOffset: number; residual: number };
  } | null>(null);

  optionsRef.current = options;
  storeRef.current = store;
  strategyRef.current = strategy;
  stateRef.current = state;

  const commitState = useCallback(
    (patch: Partial<ReadingPositionControllerState>) => {
      if (patch.navigationState !== undefined) {
        navStateRef.current = patch.navigationState;
      }
      if (!mountedRef.current) return;
      setState((previous) => ({ ...previous, ...patch }));
    },
    [],
  );

  const setNavState = useCallback(
    (event: Parameters<typeof nextNavigationState>[1]) => {
      const next = nextNavigationState(navStateRef.current, event);
      navStateRef.current = next;
      setState((previous) => ({ ...previous, navigationState: next }));
    },
    [],
  );

  const nextHistoryKey = useCallback(() => {
    historySequence += 1;
    return `hk${Date.now().toString(36)}_${historySequence}`;
  }, []);

  const selectorFor = useCallback(
    (unitId: string) => `${unitSelector}[${unitIdAttribute}="${unitId}"]`,
    [unitSelector, unitIdAttribute],
  );

  const measureUnits = useCallback((): MeasuredUnit[] => {
    if (typeof document === "undefined") return [];
    const nodes = Array.from(document.querySelectorAll(unitSelector)) as HTMLElement[];
    const viewportBottom = typeof window === "undefined" ? 0 : window.innerHeight;
    return nodes
      .map((node) => {
        const rect = node.getBoundingClientRect();
        const unitId = node.getAttribute(unitIdAttribute) ?? "";
        const ordinal = Number(node.getAttribute(ordinalAttribute) ?? "0");
        return {
          unitId,
          ordinal: Number.isFinite(ordinal) ? ordinal : 0,
          top: rect.top,
          bottom: rect.bottom,
          visible:
            rect.height > 0 &&
            rect.bottom > 0 &&
            rect.top < Math.max(viewportBottom, rect.bottom),
        } satisfies MeasuredUnit;
      })
      .filter((unit) => unit.unitId.length > 0);
  }, [unitSelector, unitIdAttribute, ordinalAttribute]);

  const ordinalOf = useCallback(
    (unitId: string): number => {
      if (typeof document !== "undefined") {
        const node = document.querySelector(selectorFor(unitId)) as HTMLElement | null;
        const raw = node?.getAttribute(ordinalAttribute);
        const parsed = raw === null || raw === undefined ? Number.NaN : Number(raw);
        if (Number.isFinite(parsed)) return parsed;
      }
      return optionsRef.current.getUnit(unitId)?.ordinal ?? 0;
    },
    [selectorFor, ordinalAttribute],
  );

  const currentLocator = useCallback((): ReadingLocator | null => {
    const current = stateRef.current;
    const active = activeRef.current;
    if (!current.stream || !current.catalog || !active) return null;
    const locator: ReadingLocator = {
      stream_id: current.stream,
      catalog_sha: current.catalog,
      unit_id: active.unitId,
    };
    return (strategyRef.current.validate ?? isReadingLocator)(locator) ? locator : null;
  }, []);

  const writeUrl = useCallback(
    (locator: ReadingLocator, mode: "push" | "replace", historyKey: string) => {
      if (typeof window === "undefined") return;
      const url = strategyRef.current.build(locator);
      if (mode === "push") {
        window.history.pushState({ readingHistoryKey: historyKey }, "", url);
      } else {
        window.history.replaceState({ ...window.history.state, readingHistoryKey: historyKey }, "", url);
      }
    },
    [],
  );

  const saveHistoryEntry = useCallback(
    (relativeOffset: number, focusId: string | null, sourceExpanded: boolean) => {
      const locator = currentLocator();
      if (!locator || !historyKeyRef.current) return;
      storeRef.current.saveEntry({
        history_key: historyKeyRef.current,
        locator,
        relative_offset: relativeOffset,
        focus_id: focusId,
        source_expanded: sourceExpanded,
      });
    },
    [currentLocator],
  );

  /** 测量某个 unit 相对参考线的位置；用于持久化 unit 内相对位置而非固定 0。 */
  const measureRelativeOffset = useCallback(
    (unitId: string): number => {
      if (typeof document === "undefined" || typeof window === "undefined") return 0;
      const node = document.querySelector(selectorFor(unitId)) as HTMLElement | null;
      if (!node) return 0;
      const rect = node.getBoundingClientRect();
      const referenceY = referenceLineFor(window.innerHeight, headerHeight, referenceRatio);
      return relativeOffsetWithin({ top: rect.top, bottom: rect.bottom }, referenceY);
    },
    [selectorFor, headerHeight, referenceRatio],
  );

  const scheduleSettleUrl = useCallback(() => {
    if (typeof window === "undefined") return;
    if (settleTimerRef.current !== null) {
      window.clearTimeout(settleTimerRef.current);
    }
    settleTimerRef.current = window.setTimeout(() => {
      settleTimerRef.current = null;
      const locator = currentLocator();
      if (!locator) return;
      // 自然滚动 settle 时按当前 active unit 的实测相对位置持久化，供
      // back/forward 与刷新恢复 unit 内位置，而不是总回到段首。
      const offset = measureRelativeOffset(locator.unit_id);
      writeUrl(locator, "replace", historyKeyRef.current);
      saveHistoryEntry(offset, null, false);
    }, settleDelayMs);
  }, [currentLocator, writeUrl, saveHistoryEntry, measureRelativeOffset, settleDelayMs]);

  const scrollToTarget = useCallback(
    (unitId: string, relativeOffset: number) => {
      const custom = optionsRef.current.scrollToUnit;
      if (custom) {
        custom(unitId, relativeOffset);
        return;
      }
      if (typeof document === "undefined" || typeof window === "undefined") return;
      const node = document.querySelector(selectorFor(unitId)) as HTMLElement | null;
      if (!node) return;
      const rect = node.getBoundingClientRect();
      const referenceY = referenceLineFor(window.innerHeight,
        optionsRef.current.headerHeight ?? 0, optionsRef.current.referenceRatio ?? 0.3);
      // 目标 unit 顶部对齐参考线时，sub-pixel 取整可能把直线留在上一段边界上；
      // 至少把直线放进目标段内 2px（不超过段高一半），保证 active unit 是被定位段。
      const inset = Math.min(2, rect.height / 2);
      const offsetPx = Math.max(rect.height * relativeOffset, inset);
      const targetTop = window.scrollY + rect.top - referenceY + offsetPx;
      const behavior: ScrollBehavior = prefersReducedMotion() ? "auto" : "auto";
      window.scrollTo({ top: targetTop, behavior });
      return targetTop - window.scrollY;
    },
    [selectorFor, headerHeight, referenceRatio],
  );

  const hasUnloadedSpace = useCallback((unitId: string, delta: number) => {
    const edges = optionsRef.current.getWindowEdges?.(unitId);
    return Boolean(delta < 0 ? edges?.hasPrevious : edges?.hasNext);
  }, []);

  const rememberLayoutAnchor = useCallback((unitId: string, requested?: { relativeOffset: number; residual: number }) => {
    if (!optionsRef.current.preserveLayoutPosition || typeof window === "undefined") return false;
    // A temporary page boundary must not turn the requested offset into the
    // browser's clamped position before adjacent content has arrived.
    if (!requested && layoutAnchorRef.current?.pending) return true;
    const node = document.querySelector<HTMLElement>(selectorFor(unitId));
    if (!node) return false;
    const rect = node.getBoundingClientRect();
    const referenceLine = referenceLineFor(window.innerHeight,
      optionsRef.current.headerHeight ?? 0, optionsRef.current.referenceRatio ?? 0.3);
    const pending = requested && Math.abs(requested.residual) > 0.5 &&
      hasUnloadedSpace(unitId, requested.residual) ? requested : undefined;
    const offset = pending
      ? Math.max(rect.height * pending.relativeOffset, Math.min(2, rect.height / 2)) / rect.height
      : relativeOffsetWithin(rect, referenceLine);
    layoutAnchorRef.current = {
      unitId, offset, referenceLine, pending,
      documentPoint: window.scrollY + rect.top + rect.height * offset,
    };
    return Boolean(pending);
  }, [selectorFor, hasUnloadedSpace]);

  const preserveLayoutAnchor = useCallback(() => {
    const anchor = layoutAnchorRef.current;
    if (!optionsRef.current.preserveLayoutPosition || !anchor || typeof window === "undefined") return;
    const node = document.querySelector<HTMLElement>(selectorFor(anchor.unitId));
    if (!node) return;
    const rect = node.getBoundingClientRect();
    const referenceLine = referenceLineFor(window.innerHeight,
      optionsRef.current.headerHeight ?? 0, optionsRef.current.referenceRatio ?? 0.3);
    const offset = anchor.pending
      ? Math.max(rect.height * anchor.pending.relativeOffset, Math.min(2, rect.height / 2)) / rect.height
      : anchor.offset;
    const documentPoint = window.scrollY + rect.top + rect.height * offset;
    // Document coordinates separate layout growth from the user's own scroll.
    // Applying only this delta keeps wheel/touch movement intact while newly
    // prepended paragraphs, loading notices and remeasured units change height.
    const delta = documentPoint - anchor.documentPoint - (referenceLine - anchor.referenceLine) +
      (anchor.pending?.residual ?? 0);
    const before = window.scrollY;
    if (Math.abs(delta) > 0.5) window.scrollBy({ top: delta, behavior: "auto" });
    const residual = delta - (window.scrollY - before);
    const pending = anchor.pending && Math.abs(residual) > 0.5 && hasUnloadedSpace(anchor.unitId, residual)
      ? { ...anchor.pending, residual } : undefined;
    layoutAnchorRef.current = { ...anchor, offset, documentPoint, referenceLine, pending };
    if (anchor.pending && !pending) {
      // The requested point is now reachable, or the current page flags prove
      // this is the real stream boundary. Both are legitimate completion.
      rememberLayoutAnchor(anchor.unitId);
      commitState({ navigationState: "idle" });
    }
  }, [selectorFor, hasUnloadedSpace, rememberLayoutAnchor, commitState]);

  const waitForDom = useCallback(
    (unitId: string, seq: number): Promise<boolean> =>
      new Promise((resolve) => {
        if (typeof requestAnimationFrame !== "function") {
          resolve(false);
          return;
        }
        let frames = 0;
        const step = () => {
          if (seq !== requestSeqRef.current) {
            resolve(false);
            return;
          }
          if (document.querySelector(selectorFor(unitId))) {
            resolve(true);
            return;
          }
          frames += 1;
          if (frames > restoreFrameBudget) {
            resolve(false);
            return;
          }
          requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      }),
    [selectorFor, restoreFrameBudget],
  );

  /**
   * 在第一个 await 之前分配操作序号，使任何更新的导航/用户交互立即作废本次操作。
   * 所有异步回调（locate/loadWindow/resolveStart/DOM-ready）都必须用同一序号 fence。
   */
  const beginOperation = useCallback((): number => {
    requestSeqRef.current += 1;
    operationAbortRef.current?.abort();
    operationAbortRef.current = new AbortController();
    if (settleTimerRef.current !== null && typeof window !== "undefined") {
      window.clearTimeout(settleTimerRef.current);
      settleTimerRef.current = null;
    }
    if (layoutAnchorRef.current?.pending) {
      layoutAnchorRef.current = null;
      if (activeRef.current) rememberLayoutAnchor(activeRef.current.unitId);
    }
    return requestSeqRef.current;
  }, [rememberLayoutAnchor]);

  const applyLocator = useCallback(
    async (locator: ReadingLocator, detail: RestoreDetail, preallocatedSeq?: number) => {
      if (!(strategyRef.current.validate ?? isReadingLocator)(locator)) {
        commitState({ issue: readingIssue("invalid_unit", "refusing non-typed locator") });
        return;
      }
      const seq = preallocatedSeq ?? beginOperation();
      if (seq !== requestSeqRef.current) return;
      setNavState(detail.push ? "begin_navigation" : "begin_restore");
      commitState({ issue: null });

      let located: ReadingLocateResult | null;
      try {
        located = await optionsRef.current.locate(locator, operationAbortRef.current?.signal);
      } catch (error) {
        if (seq !== requestSeqRef.current || !mountedRef.current) return;
        commitState({
          navigationState: "idle",
          issue: readingIssue("snapshot_mismatch", `locate failed: ${errorMessage(error)}`),
        });
        return;
      }
      if (seq !== requestSeqRef.current || !mountedRef.current) return;
      if (!located || located.locator.stream_id !== locator.stream_id ||
          located.locator.catalog_sha !== locator.catalog_sha || located.locator.unit_id !== locator.unit_id ||
          !located.unitIds.includes(locator.unit_id)) {
        commitState({
          navigationState: "idle",
          issue: readingIssue("snapshot_mismatch", "locate returned no page for locator"),
        });
        return;
      }

      // 就绪等待期间不提交 URL/history/controller locator：用户滚动、loadWindow
      // 失败或 DOM 超时一旦取消本次操作，旧状态原样保留，不会出现 URL 指向已取消
      // 目标而 active unit 仍停留在旧段的错配。
      try {
        await optionsRef.current.loadWindow?.(locator);
      } catch {
        /* 加载失败保持已读正文，后续显式错误由窗口报告 */
      }
      if (seq !== requestSeqRef.current || !mountedRef.current) return;

      const ready = await waitForDom(locator.unit_id, seq);
      if (seq !== requestSeqRef.current || !mountedRef.current) return;
      if (!ready) {
        commitState({
          navigationState: "idle",
          issue: readingIssue("invalid_unit", "target unit did not mount in time"),
        });
        return;
      }

      // 所有异步等待完成且序号仍为当前：同步原子提交 URL/history/controller。
      const key = detail.historyKey ?? (detail.push ? nextHistoryKey() : historyKeyRef.current);
      historyKeyRef.current = key;
      const ordinal = ordinalOf(locator.unit_id);
      activeRef.current = { unitId: locator.unit_id, ordinal };
      const unit = optionsRef.current.getUnit(locator.unit_id) ?? null;
      commitState({
        stream: locator.stream_id,
        catalog: locator.catalog_sha,
        locator,
        activeUnitId: locator.unit_id,
        activeOrdinal: ordinal,
        activeUnit: unit,
      });
      writeUrl(locator, detail.push ? "push" : "replace", key);
      const residual = scrollToTarget(locator.unit_id, detail.relativeOffset) ?? 0;
      const pending = rememberLayoutAnchor(locator.unit_id, { relativeOffset: detail.relativeOffset, residual });
      if (!pending) commitState({ navigationState: "idle" });
      optionsRef.current.onActiveUnitChange?.(unit);
      storeRef.current.saveEntry({
        history_key: key,
        locator,
        relative_offset: detail.relativeOffset,
        focus_id: detail.focusId,
        source_expanded: detail.sourceExpanded,
      });

      if (detail.focusId && typeof document !== "undefined") {
        const trigger = document.querySelector(
          `[data-focus-id="${detail.focusId}"]`,
        ) as HTMLElement | null;
        trigger?.focus();
      }
      if (detail.push && !detail.focusId && typeof document !== "undefined") {
        const target = document.querySelector(selectorFor(locator.unit_id)) as HTMLElement | null;
        if (target) {
          target.tabIndex = -1;
          target.focus({ preventScroll: true });
        }
      }
    },
    [beginOperation, commitState, setNavState, nextHistoryKey, writeUrl, waitForDom, scrollToTarget, rememberLayoutAnchor, ordinalOf, selectorFor],
  );

  const refreshActive = useCallback(() => {
    if (!mountedRef.current || typeof window === "undefined") return;
    preserveLayoutAnchor();
    if (navStateRef.current === "restoring" || navStateRef.current === "navigating") {
      return;
    }
    const referenceY = referenceLineFor(window.innerHeight, headerHeight, referenceRatio);
    const chosen = selectActiveUnit(measureUnits(), referenceY);
    if (chosen) {
      rememberLayoutAnchor(chosen.unitId);
      const changed = chosen.unitId !== activeRef.current?.unitId;
      if (changed) {
        activeRef.current = { unitId: chosen.unitId, ordinal: chosen.ordinal };
        commitState({
          activeUnitId: chosen.unitId,
          activeOrdinal: chosen.ordinal,
          activeUnit: optionsRef.current.getUnit(chosen.unitId) ?? null,
        });
        optionsRef.current.onActiveUnitChange?.(optionsRef.current.getUnit(chosen.unitId) ?? null);
      }
      if (navStateRef.current !== "idle") {
        setNavState("settled");
      }
      // Scrolling within one long paragraph also changes the return position.
      scheduleSettleUrl();
    }
  }, [
    commitState,
    setNavState,
    measureUnits,
    headerHeight,
    referenceRatio,
    scheduleSettleUrl,
    preserveLayoutAnchor,
    rememberLayoutAnchor,
  ]);

  const onUserIntent = useCallback(() => {
    if (settleTimerRef.current !== null && typeof window !== "undefined") {
      window.clearTimeout(settleTimerRef.current);
      settleTimerRef.current = null;
    }
    schedulerRef.current?.cancel();
    layoutAnchorRef.current = null;
    if (activeRef.current) rememberLayoutAnchor(activeRef.current.unitId);
    if (navStateRef.current === "restoring" || navStateRef.current === "navigating") {
      requestSeqRef.current += 1;
      operationAbortRef.current?.abort();
      setNavState("user_scrolled");
    }
  }, [setNavState, rememberLayoutAnchor]);

  const restoreFromUrlInternal = useCallback(async () => {
    if (typeof window === "undefined") return;
    const parsed = strategyRef.current.parse(
      `${window.location.pathname}${window.location.search}`,
    );
    if (!parsed.ok) {
      commitState({ issue: parsed.issue, navigationState: "idle" });
      return;
    }
    const location = parsed.location;
    if (location.unit_id === null) {
      // 在 await 之前 fence：迟到的 resolveStart 不得覆盖之后发生的导航/用户交互。
      const seq = beginOperation();
      if (seq !== requestSeqRef.current) return;
      setNavState("begin_restore");
      commitState({ issue: null });
      const resolveStart = optionsRef.current.resolveStart;
      let start: ReadingLocator | null;
      try {
        start = resolveStart
          ? await resolveStart({
              stream_id: location.stream_id,
              catalog_sha: location.catalog_sha,
            })
          : null;
      } catch (error) {
        if (seq !== requestSeqRef.current || !mountedRef.current) return;
        commitState({
          navigationState: "idle",
          issue: readingIssue("snapshot_mismatch", `start resolution failed: ${errorMessage(error)}`),
        });
        return;
      }
      if (seq !== requestSeqRef.current || !mountedRef.current) return;
      if (!start) {
        commitState({
          issue: readingIssue("missing_unit", "URL has no at and no start resolver"),
          navigationState: "idle",
        });
        return;
      }
      await applyLocator(
        start,
        {
          relativeOffset: 0,
          focusId: null,
          sourceExpanded: false,
          historyKey: historyKeyRef.current || undefined,
          push: false,
        },
        seq,
      );
      return;
    }
    const locator: ReadingLocator = {
      stream_id: location.stream_id,
      catalog_sha: location.catalog_sha,
      unit_id: location.unit_id,
    };
    const entry = storeRef.current.findEntry(locator, historyKeyRef.current ? [historyKeyRef.current] : []);
    await applyLocator(locator, {
      relativeOffset: entry?.relative_offset ?? 0,
      focusId: entry?.focus_id ?? null,
      sourceExpanded: entry?.source_expanded ?? false,
      historyKey: historyKeyRef.current || undefined,
      push: false,
    });
  }, [applyLocator, beginOperation, commitState, setNavState]);

  const restoreFromUrl = useCallback(() => {
    void restoreFromUrlInternal();
  }, [restoreFromUrlInternal]);

  const navigate = useCallback(
    (action: ReadingNavigationAction) => {
      if (action.kind === "back" || action.kind === "forward") {
        void applyLocator(action.locator, {
          relativeOffset: 0,
          focusId: null,
          sourceExpanded: false,
          push: false,
        });
        return;
      }
      const active = activeRef.current;
      const offset = active ? measureRelativeOffset(active.unitId) : 0;
      saveHistoryEntry(offset, action.kind === "event" ? action.event_id : null, action.kind === "source");
      void applyLocator(action.locator, {
        relativeOffset: 0,
        focusId: action.kind === "event" ? action.event_id : null,
        sourceExpanded: action.kind === "source",
        push: true,
      });
    },
    [applyLocator, saveHistoryEntry, measureRelativeOffset],
  );

  const restoreLocator = useCallback(
    (
      locator: ReadingLocator,
      restoreOptions: { push?: boolean; relativeOffset?: number; focusId?: string | null } = {},
    ) => {
      void applyLocator(locator, {
        relativeOffset: restoreOptions.relativeOffset ?? 0,
        focusId: restoreOptions.focusId ?? null,
        sourceExpanded: false,
        push: restoreOptions.push ?? false,
      });
    },
    [applyLocator],
  );

  const rememberReturnTarget = useCallback(
    (): { token: string; locator: ReadingLocator; persisted: boolean } | null => {
      const locator = currentLocator();
      if (!locator) return null;
      saveHistoryEntry(measureRelativeOffset(locator.unit_id), null, false);
      const result = storeRef.current.rememberReturn(locator);
      if (!result.token) return null;
      return { token: result.token, locator, persisted: result.persisted };
    },
    [currentLocator, saveHistoryEntry, measureRelativeOffset],
  );

  const restoreReturnToken = useCallback(
    (token: string): ReadingLocator | null => {
      const locator = storeRef.current.resolveReturn(token);
      if (!locator) return null;
      const entry = storeRef.current.findEntry(locator);
      void applyLocator(locator, {
        relativeOffset: entry?.relative_offset ?? 0,
        focusId: entry?.focus_id ?? null,
        sourceExpanded: entry?.source_expanded ?? false,
        push: true,
      });
      return locator;
    },
    [applyLocator],
  );

  const previewEvent = useCallback((_eventId: string) => {
    // 预览是只读悬停态：不改变 active unit、不写 URL、不压返回栈。
  }, []);

  const notifyLayoutChange = useCallback((_unitId?: string) => {
    // Layout-effect notifications arrive after DOM changes but before paint.
    // Compensate now, before a new input can target the changed geometry.
    preserveLayoutAnchor();
    schedulerRef.current?.schedule(refreshActive);
  }, [preserveLayoutAnchor, refreshActive]);

  useEffect(() => {
    mountedRef.current = true;
    schedulerRef.current = createFrameScheduler();
    historyKeyRef.current = typeof window !== "undefined" && typeof window.history.state?.readingHistoryKey === "string"
      ? window.history.state.readingHistoryKey : nextHistoryKey();
    if (typeof window !== "undefined") {
      window.history.replaceState(
        { ...window.history.state, readingHistoryKey: historyKeyRef.current },
        "",
        window.location.href,
      );
    }

    const handleScroll = () => {
      if (!schedulerRef.current) return;
      schedulerRef.current.schedule(refreshActive);
    };
    const handleKeydown = (event: KeyboardEvent) => {
      if (SCROLL_KEYS.has(event.key)) onUserIntent();
    };
    const handlePopstate = (event: PopStateEvent) => {
      const key = (event.state as { readingHistoryKey?: string } | null)?.readingHistoryKey;
      if (key) historyKeyRef.current = key;
      void restoreFromUrlInternal();
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    window.addEventListener("wheel", onUserIntent, { passive: true });
    window.addEventListener("touchstart", onUserIntent, { passive: true });
    window.addEventListener("keydown", handleKeydown);
    window.addEventListener("popstate", handlePopstate);

    void restoreFromUrlInternal();

    return () => {
      mountedRef.current = false;
      layoutAnchorRef.current = null;
      requestSeqRef.current += 1;
      operationAbortRef.current?.abort();
      window.removeEventListener("scroll", handleScroll);
      window.removeEventListener("wheel", onUserIntent);
      window.removeEventListener("touchstart", onUserIntent);
      window.removeEventListener("keydown", handleKeydown);
      window.removeEventListener("popstate", handlePopstate);
      schedulerRef.current?.cancel();
      schedulerRef.current = null;
      if (settleTimerRef.current !== null) {
        window.clearTimeout(settleTimerRef.current);
        settleTimerRef.current = null;
      }
    };
  }, [nextHistoryKey, refreshActive, onUserIntent, restoreFromUrlInternal]);

  const activeUnit = state.activeUnit;
  return {
    ...state,
    activeUnit,
    narrativeTime: activeUnit?.narrativeTime ?? null,
    contextEntities: activeUnit?.contextEntities ?? [],
    storageAvailable,
    navigate,
    restoreLocator,
    restoreFromUrl,
    rememberReturnTarget,
    restoreReturnToken,
    previewEvent,
    notifyLayoutChange,
  };
}
