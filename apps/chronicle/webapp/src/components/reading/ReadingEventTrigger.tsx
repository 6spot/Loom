// C2-R2-T13 正文事件词触发入口与轻量预览。
//
// 合同见 reading-experience.md §5 与 continuous-reading.md §7：
//   - 只消费程序切好的结构化 span；resolved 且绑定 canonical event 才可操作，
//     ambiguous/unresolved 不做唯一链接、不按名称静默跳转；
//   - hover（约 180ms 打开 / 约 120ms 关闭，进入卡片不闪退）、键盘 focus、
//     触屏 tap 等价可达；Escape 关闭并把焦点还给触发词，Tab 进入卡片按钮；
//   - 只在 hover/focus/tap 时按需请求 preview/targets；同一时刻只有一个预览，
//     关闭/换词后迟到的响应不得覆盖新预览，也不改变阅读时间；
//   - 载入失败保留正文并允许重试；遵守 reduced-motion。
//
// 组件本身不持 URL/history/阅读时间：通过 typed loader 与 onNavigate 交给 T15
// 注入的 T09 client / T12 controller。

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type {
  EventPreview,
  EventTarget,
  EventTargetPage,
  ReadingEventSegment,
  ReadingLocator,
  ReadingNavigationAction,
} from "../../lib/reading-types";
import {
  eventPreviewCacheKey,
  eventTargetsCacheKey,
  readingPreviewCache,
  type ReadingPreviewCache,
} from "../../lib/reading-preview-cache";
import ReadingEventPreview from "./ReadingEventPreview";
import type { ReadingTargetPickerMode } from "./ReadingTargetPicker";
import "../../styles/reading-events.css";

export type EventPreviewLoader = (eventId: string) => Promise<EventPreview>;
export type EventTargetLoader = (eventId: string, cursor?: string | null) => Promise<EventTargetPage>;
export type EventOpenReason = "hover" | "focus" | "tap";

export interface ReadingEventTriggerProps {
  readonly segment: ReadingEventSegment;
  /** 当前 catalog 快照；与 event_id 一起构成缓存 key，旧快照不覆盖新快照。 */
  readonly catalogSha: string;
  /** 当前阅读 locator，用于「查看事件」返回位置；缺失时禁用该入口。 */
  readonly locator?: ReadingLocator | null;
  readonly loadPreview: EventPreviewLoader;
  readonly loadTargets: EventTargetLoader;
  readonly onNavigate: (action: ReadingNavigationAction) => void;
  readonly cache?: ReadingPreviewCache;
  readonly hoverOpenDelayMs?: number;
  readonly closeDelayMs?: number;
  readonly reducedMotion?: boolean;
  readonly onOpenChange?: (open: boolean) => void;
}

const DEFAULT_HOVER_OPEN_DELAY_MS = 180;
const DEFAULT_CLOSE_DELAY_MS = 120;
const CARD_WIDTH = 340;
const PREVIEW_OPEN_EVENT = "reading-event-preview:open";

function broadcastOpen(instanceId: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<string>(PREVIEW_OPEN_EVENT, { detail: instanceId }));
}

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  return "事件预览载入失败，请重试";
}

function mediaMatches(query: string): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(query).matches;
}

function useNarrowViewport(): boolean {
  const [narrow, setNarrow] = useState(() => mediaMatches("(max-width: 767px)"));
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(max-width: 767px)");
    const update = () => setNarrow(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);
  return narrow;
}

function usePrefersReducedMotion(override?: boolean): boolean {
  const [prefers, setPrefers] = useState(() => override ?? mediaMatches("(prefers-reduced-motion: reduce)"));
  useEffect(() => {
    if (override !== undefined) {
      setPrefers(override);
      return;
    }
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setPrefers(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, [override]);
  return prefers;
}

export default function ReadingEventTrigger({
  segment,
  catalogSha,
  locator = null,
  loadPreview,
  loadTargets,
  onNavigate,
  cache = readingPreviewCache,
  hoverOpenDelayMs = DEFAULT_HOVER_OPEN_DELAY_MS,
  closeDelayMs = DEFAULT_CLOSE_DELAY_MS,
  reducedMotion,
  onOpenChange,
}: ReadingEventTriggerProps) {
  const span = segment.span;
  const eventId = span.target_event_id;
  const operable = span.status === "resolved" && eventId !== null;
  const uncertainReason = span.status === "resolved" ? "no-canonical-target" : span.status;
  const reduced = usePrefersReducedMotion(reducedMotion);
  const narrow = useNarrowViewport();
  const instanceId = useId();

  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const openTimerRef = useRef<number | null>(null);
  const closeTimerRef = useRef<number | null>(null);
  const requestIdRef = useRef(0);
  const targetsRequestIdRef = useRef(0);
  const moreRequestIdRef = useRef(0);
  const openRef = useRef(false);

  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [targetsLoading, setTargetsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [targetsError, setTargetsError] = useState<string | null>(null);
  const [preview, setPreview] = useState<EventPreview | null>(null);
  const [targets, setTargets] = useState<EventTargetPage | null>(null);
  const [picker, setPicker] = useState<ReadingTargetPickerMode | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [selectedUnitId, setSelectedUnitId] = useState<string | null>(null);
  const [openReason, setOpenReason] = useState<EventOpenReason | null>(null);
  const [cardPosition, setCardPosition] = useState<{ top: number; left: number } | null>(null);

  const clearTimers = useCallback(() => {
    if (openTimerRef.current !== null) {
      window.clearTimeout(openTimerRef.current);
      openTimerRef.current = null;
    }
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  const close = useCallback(
    (restoreFocus: boolean) => {
      clearTimers();
      requestIdRef.current += 1;
      targetsRequestIdRef.current += 1;
      moreRequestIdRef.current += 1;
      setOpen(false);
      setPicker(null);
      setLoading(false);
      setTargetsLoading(false);
      setLoadingMore(false);
      if (restoreFocus) triggerRef.current?.focus();
    },
    [clearTimers],
  );

  const loadData = useCallback(
    async (id: string) => {
      requestIdRef.current += 1;
      const token = requestIdRef.current;
      targetsRequestIdRef.current += 1;
      const targetsToken = targetsRequestIdRef.current;
      moreRequestIdRef.current += 1;
      setLoading(true);
      setTargetsLoading(true);
      setError(null);
      setTargetsError(null);
      setPreview(null);
      setTargets(null);
      setPicker(null);
      setSelectedUnitId(null);

      const previewRequest = cache
        .load(eventPreviewCacheKey(catalogSha, id), () => loadPreview(id))
        .then(
          (value) => {
            if (requestIdRef.current === token) setPreview(value);
            return value;
          },
          (cause: unknown) => {
            if (requestIdRef.current === token) setError(errorMessage(cause));
            throw cause;
          },
        );
      // preview 与 targets 各自独立作废：targets 失败不得清空已成功的 preview。
      const targetsRequest = cache
        .load(eventTargetsCacheKey(catalogSha, id), () => loadTargets(id))
        .then(
          (value) => {
            if (targetsRequestIdRef.current === targetsToken) setTargets(value);
            return value;
          },
          (cause: unknown) => {
            if (targetsRequestIdRef.current === targetsToken) setTargetsError(errorMessage(cause));
            return null;
          },
        );

      await Promise.allSettled([previewRequest, targetsRequest]);
      if (requestIdRef.current === token) setLoading(false);
      if (targetsRequestIdRef.current === targetsToken) setTargetsLoading(false);
    },
    [cache, catalogSha, loadPreview, loadTargets],
  );

  const openPreview = useCallback(
    (why: EventOpenReason) => {
      if (!operable || eventId === null) return;
      clearTimers();
      setOpen(true);
      setOpenReason(why);
      broadcastOpen(instanceId);
      if (!preview && !loading) void loadData(eventId);
    },
    [operable, eventId, clearTimers, preview, loading, loadData, instanceId],
  );

  useEffect(() => {
    openRef.current = open;
    onOpenChange?.(open);
  }, [open, onOpenChange]);

  // span/事件变化：作废旧请求并重置，避免上一个事件的数据或迟到响应用到新词。
  useEffect(() => {
    requestIdRef.current += 1;
    targetsRequestIdRef.current += 1;
    moreRequestIdRef.current += 1;
    setOpen(false);
    setPreview(null);
    setTargets(null);
    setError(null);
    setTargetsError(null);
    setLoading(false);
    setTargetsLoading(false);
    setPicker(null);
  }, [eventId, span.span_id]);

  // 同一时刻一个预览：其他触发词打开时，本预览关闭（不抢焦点）。
  useEffect(() => {
    if (typeof window === "undefined") return;
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      if (detail !== instanceId) close(false);
    };
    window.addEventListener(PREVIEW_OPEN_EVENT, handler);
    return () => window.removeEventListener(PREVIEW_OPEN_EVENT, handler);
  }, [instanceId, close]);

  // Escape 关闭并回到触发词；点击卡片/触发词之外关闭。
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close(true);
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && (triggerRef.current?.contains(target) || cardRef.current?.contains(target))) return;
      close(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, [open, close]);

  // 桌面卡片定位：跟随触发词并在视口内夹取，窄屏由 CSS 变成底部面板。
  useEffect(() => {
    if (!open || narrow) {
      setCardPosition(null);
      return;
    }
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect || typeof window === "undefined") return;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - CARD_WIDTH - 8));
    const top = Math.min(rect.bottom + 8, Math.max(8, window.innerHeight - 16));
    setCardPosition({ top, left });
  }, [open, narrow]);

  const handleTriggerPointerEnter = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.pointerType === "touch") return;
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    if (openRef.current) return;
    if (openTimerRef.current !== null) window.clearTimeout(openTimerRef.current);
    openTimerRef.current = window.setTimeout(() => openPreview("hover"), hoverOpenDelayMs);
  };

  const handleTriggerPointerLeave = () => {
    if (openTimerRef.current !== null) {
      window.clearTimeout(openTimerRef.current);
      openTimerRef.current = null;
    }
    if (!openRef.current) return;
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    closeTimerRef.current = window.setTimeout(() => close(false), closeDelayMs);
  };

  const handleCardPointerEnter = () => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  };

  const handleCardPointerLeave = () => {
    if (!openRef.current) return;
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    closeTimerRef.current = window.setTimeout(() => close(false), closeDelayMs);
  };

  const handleTriggerClick = () => {
    if (!operable) return;
    if (!openRef.current) openPreview("tap");
  };

  const handleTriggerFocus = () => {
    if (!operable) return;
    if (!openRef.current) openPreview("focus");
  };

  const handleTriggerBlur = () => {
    if (!openRef.current) return;
    window.setTimeout(() => {
      const active = document.activeElement;
      if (triggerRef.current?.contains(active)) return;
      if (cardRef.current?.contains(active)) return;
      close(false);
    }, 0);
  };

  const handleTriggerKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "Tab" || event.shiftKey || !openRef.current) return;
    const first = cardRef.current?.querySelector<HTMLElement>(
      "button:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
    );
    if (first) {
      event.preventDefault();
      first.focus();
    }
  };

  const handleRetry = () => {
    if (eventId === null) return;
    cache.delete(eventPreviewCacheKey(catalogSha, eventId));
    cache.delete(eventTargetsCacheKey(catalogSha, eventId));
    void loadData(eventId);
  };

  // 只重取 targets，不丢弃已成功的 preview；供错误提示与「定位/其他记载」共用。
  const handleRetryTargets = useCallback(() => {
    if (eventId === null) return;
    cache.delete(eventTargetsCacheKey(catalogSha, eventId));
    targetsRequestIdRef.current += 1;
    const token = targetsRequestIdRef.current;
    setTargetsError(null);
    setTargets(null);
    setTargetsLoading(true);
    void cache
      .load(eventTargetsCacheKey(catalogSha, eventId), () => loadTargets(eventId))
      .then(
        (value) => {
          if (targetsRequestIdRef.current === token) setTargets(value);
        },
        (cause: unknown) => {
          if (targetsRequestIdRef.current === token) setTargetsError(errorMessage(cause));
        },
      )
      .finally(() => {
        if (targetsRequestIdRef.current === token) setTargetsLoading(false);
      });
  }, [cache, catalogSha, eventId, loadTargets]);

  const handleViewEvent = () => {
    if (eventId === null || locator === null) return;
    onNavigate({ kind: "event", locator, event_id: eventId });
    close(false);
  };

  const chooseTarget = (target: EventTarget) => {
    setSelectedUnitId(target.unit_id);
    const action: ReadingNavigationAction =
      target.relation === "current"
        ? { kind: "locate", locator: target.locator }
        : { kind: "source", locator: target.locator };
    onNavigate(action);
    close(false);
  };

  const handleLocate = () => {
    setPicker("locate");
    if (targetsError) {
      // 错误已可见；这里再取一次而不是静默无动作。
      handleRetryTargets();
      return;
    }
    if (!targets) return;
    const currentTargets = targets.targets.filter((target) => target.relation === "current");
    if (targets.current_count === 1 && currentTargets.length === 1) {
      chooseTarget(currentTargets[0]);
      return;
    }
    if (targets.has_more && currentTargets.length === 0) void handleLoadMore();
  };

  const handleOtherRecords = () => {
    setPicker("other");
    if (targetsError) handleRetryTargets();
  };

  const handleLoadMore = async () => {
    if (eventId === null || !targets || !targets.next_cursor || loadingMore) return;
    moreRequestIdRef.current += 1;
    const token = moreRequestIdRef.current;
    const cursor = targets.next_cursor;
    setLoadingMore(true);
    try {
      const next = await cache.load(
        eventTargetsCacheKey(catalogSha, `${eventId}:${cursor}`),
        () => loadTargets(eventId, cursor),
      );
      if (moreRequestIdRef.current !== token) return;
      setTargets((current) =>
        current
          ? {
              ...current,
              targets: [...current.targets, ...next.targets],
              current_count: next.current_count,
              mention_count: next.mention_count,
              next_cursor: next.next_cursor,
              has_more: next.has_more,
            }
          : next,
      );
    } catch {
      // 分页失败保留已取回的位置，用户可再次点击。
    } finally {
      if (moreRequestIdRef.current === token) setLoadingMore(false);
    }
  };

  const trigger = operable ? (
    <button
      type="button"
      ref={triggerRef}
      className="rev-trigger"
      data-test="reading-event-trigger"
      data-span={span.span_id}
      data-event-id={eventId ?? ""}
      data-status={span.status}
      data-relation={span.relation}
      data-open={open}
      aria-haspopup="dialog"
      aria-expanded={open}
      onClick={handleTriggerClick}
      onFocus={handleTriggerFocus}
      onBlur={handleTriggerBlur}
      onKeyDown={handleTriggerKeyDown}
      onPointerEnter={handleTriggerPointerEnter}
      onPointerLeave={handleTriggerPointerLeave}
    >
      {segment.text}
    </button>
  ) : (
    <span
      className="rev-trigger rev-trigger-uncertain"
      data-test="reading-event-trigger-uncertain"
      data-span={span.span_id}
      data-status={span.status}
      data-relation={span.relation}
      data-reason={uncertainReason}
      role="note"
      aria-label={`${segment.text}（未确认事件，无唯一事件链接）`}
      title="未确认事件：不提供唯一事件链接"
    >
      {segment.text}
    </span>
  );

  const card =
    open && operable ? (
      <div
        ref={cardRef}
        className="rev-card"
        data-test="reading-event-preview"
        data-variant={narrow ? "panel" : "card"}
        data-event-id={eventId ?? ""}
        data-span={span.span_id}
        data-open-reason={openReason ?? ""}
        data-reduced-motion={reduced ? "true" : "false"}
        role="dialog"
        aria-label={preview?.name?.trim() || segment.text}
        style={cardPosition ?? undefined}
        onPointerEnter={handleCardPointerEnter}
        onPointerLeave={handleCardPointerLeave}
      >
        <button
          type="button"
          className="rev-close"
          data-test="reading-event-preview-close"
          aria-label="关闭事件预览"
          onClick={() => close(true)}
        >
          ×
        </button>
        <ReadingEventPreview
          fallbackName={segment.text}
          preview={preview}
          targets={targets}
          loading={loading}
          error={error}
          targetsError={targetsError}
          targetsLoading={targetsLoading}
          picker={picker}
          selectedUnitId={selectedUnitId}
          canViewEvent={locator !== null}
          onRetry={handleRetry}
          onRetryTargets={handleRetryTargets}
          onViewEvent={handleViewEvent}
          onLocate={handleLocate}
          onOtherRecords={handleOtherRecords}
          onChooseTarget={chooseTarget}
          onLoadMoreTargets={() => void handleLoadMore()}
          loadingMoreTargets={loadingMore}
        />
      </div>
    ) : null;

  return (
    <>
      {trigger}
      {card && typeof document !== "undefined" ? createPortal(card, document.body) : null}
    </>
  );
}
