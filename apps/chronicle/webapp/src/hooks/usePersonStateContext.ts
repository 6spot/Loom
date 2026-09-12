// C2-R3-T13 阅读页人物／地点阶段联动的唯一订阅点。
//
// Contract owner: apps/chronicle/docs/person-state-reading.md §7–8.
//
// 现有 `useReadingPosition` 仍唯一拥有 active paragraph／unit 与导航；本模块只
// *订阅* 那个 locator，按段取得一份有界的人物／地点状态摘要，不为每个人发一次
// 请求，也不建立第二套滚动或 history 控制器。
//
// 两条共享路径共用同一份 key/迟到/有界缓存规则：
//
//  - 综合历史（主阅读）：数据已随 `HistoryParagraph`（version/paragraph/phase）
//    一次返回，本 hook 只做确定性投影与 LRU 缓存；段落一换立即换成新段的空态，
//    绝不闪现上一段身份，空段清空。
//  - 来源阅读：`/api/v1/public/reading-streams/.../people` 由 T09/T10 typed
//    client 读取，携带完整 `{stream_id, catalog_sha, unit_id}` locator；切换
//    unit 时先 abort 旧请求，迟到响应按 key 丢弃，不覆盖新段。
//
// 详情与原文按需：这里只取摘要页，不在默认展开区请求逐人 states/evidence。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getReadingPeople,
  PersonStateAbortError,
  PersonStateApiError,
  personStateKeys,
} from "../lib/person-state-api";
import type {
  PersonStateLocator,
  PersonSummary,
  PhaseSummary,
  UnitPeoplePage,
} from "../lib/person-state-types";
import type { HistoryEntity, HistoryParagraph } from "../lib/history-api";
import type { ReadingStateFact } from "../components/reading/ReadingContextPanel";
import { personStatePhaseKey, type HistoryPhaseLocator } from "../lib/queries";

// ---------------------------------------------------------------------------
// 有界缓存（最多 100 个位置或 2 MiB，LRU 回收）
// ---------------------------------------------------------------------------

export const PERSON_STATE_CONTEXT_MAX_ENTRIES = 100;
export const PERSON_STATE_CONTEXT_MAX_BYTES = 2 * 1024 * 1024;

export interface PersonStateContextView {
  readonly key: string;
  readonly locator: HistoryPhaseLocator;
  readonly phaseId: string | null;
  readonly status: "ready" | "empty";
  readonly entities: readonly HistoryEntity[];
  readonly stateFacts: Readonly<Record<string, readonly ReadingStateFact[]>>;
}

export function historyPhaseContextKey(locator: HistoryPhaseLocator): string {
  return personStatePhaseKey(locator).join("|");
}

/** 从已取得的一段综合正文确定性投影当前段落的人物／地点状态。 */
export function buildHistoryPhaseContext(
  version: string,
  paragraph: HistoryParagraph,
): PersonStateContextView {
  const locator: HistoryPhaseLocator = {
    version,
    paragraph_id: paragraph.id,
    phase_id: paragraph.phase_id ?? null,
  };
  const entities = paragraph.entities ?? [];
  const stateFacts: Record<string, readonly ReadingStateFact[]> = {};
  for (const entity of entities) {
    stateFacts[entity.id] = entity.states ?? [];
  }
  return {
    key: historyPhaseContextKey(locator),
    locator,
    phaseId: locator.phase_id,
    status: entities.length > 0 ? "ready" : "empty",
    entities,
    stateFacts,
  };
}

interface CacheCell {
  readonly value: PersonStateContextView;
  readonly bytes: number;
}

/**
 * 简单的插入序 LRU：超过条目或字节上限时回收最旧项。它只缓存已经编译好的
 * 投影，不发起任何请求，也不把来源与综合两种 locator 混在同一命名空间。
 */
export class PersonStateContextCache {
  private readonly cells = new Map<string, CacheCell>();
  private bytes = 0;

  constructor(
    private readonly maxEntries: number = PERSON_STATE_CONTEXT_MAX_ENTRIES,
    private readonly maxBytes: number = PERSON_STATE_CONTEXT_MAX_BYTES,
  ) {}

  get(key: string): PersonStateContextView | null {
    const cell = this.cells.get(key);
    if (!cell) return null;
    // refresh recency
    this.cells.delete(key);
    this.cells.set(key, cell);
    return cell.value;
  }

  set(key: string, value: PersonStateContextView): void {
    const bytes = Math.max(1, key.length + value.entities.length * 256);
    const previous = this.cells.get(key);
    if (previous) {
      this.bytes -= previous.bytes;
      this.cells.delete(key);
    }
    this.cells.set(key, { value, bytes });
    this.bytes += bytes;
    while (
      this.cells.size > this.maxEntries ||
      (this.bytes > this.maxBytes && this.cells.size > 1)
    ) {
      const oldest = this.cells.keys().next().value as string | undefined;
      if (oldest === undefined) break;
      this.evict(oldest);
    }
  }

  private evict(key: string): void {
    const cell = this.cells.get(key);
    if (!cell) return;
    this.cells.delete(key);
    this.bytes -= cell.bytes;
  }

  clear(): void {
    this.cells.clear();
    this.bytes = 0;
  }

  get size(): number {
    return this.cells.size;
  }

  get byteSize(): number {
    return this.bytes;
  }
}

export interface HistoryPersonStateContext {
  readonly status: "loading" | "ready" | "empty";
  readonly key: string | null;
  readonly locator: HistoryPhaseLocator | null;
  readonly phaseId: string | null;
  readonly entities: readonly HistoryEntity[];
  readonly stateFacts: Readonly<Record<string, readonly ReadingStateFact[]>>;
}

const EMPTY_HISTORY_CONTEXT: HistoryPersonStateContext = {
  status: "loading",
  key: null,
  locator: null,
  phaseId: null,
  entities: [],
  stateFacts: {},
};

/**
 * 订阅唯一阅读 controller 的 active 综合段落。`paragraph` 为 `null` 表示正文窗口
 * 仍在定位；一旦段落出现就同步给出该段的实体状态，段落切换时旧上下文立即消失。
 */
export function useHistoryPersonStateContext(
  version: string | null,
  paragraph: HistoryParagraph | null | undefined,
  cache?: PersonStateContextCache,
): HistoryPersonStateContext {
  const storeRef = useRef<PersonStateContextCache | null>(null);
  if (!storeRef.current) storeRef.current = cache ?? new PersonStateContextCache();
  const store = storeRef.current;

  return useMemo(() => {
    if (!version || !paragraph) return EMPTY_HISTORY_CONTEXT;
    const key = historyPhaseContextKey({
      version,
      paragraph_id: paragraph.id,
      phase_id: paragraph.phase_id ?? null,
    });
    const cached = store.get(key);
    const context = cached ?? buildHistoryPhaseContext(version, paragraph);
    if (!cached) store.set(key, context);
    return {
      status: context.status,
      key: context.key,
      locator: context.locator,
      phaseId: context.phaseId,
      entities: context.entities,
      stateFacts: context.stateFacts,
    };
  }, [store, version, paragraph]);
}

// ---------------------------------------------------------------------------
// 来源阅读：T09/T10 typed client
// ---------------------------------------------------------------------------

export interface SourcePersonStateContext {
  readonly key: string | null;
  readonly status: "loading" | "ready" | "empty" | "error";
  readonly people: readonly PersonSummary[];
  readonly phases: readonly PhaseSummary[];
  readonly error: string | null;
  readonly hasMorePeople: boolean;
  retry(): void;
  loadMorePeople(): void;
}

interface SourceState {
  readonly key: string | null;
  readonly status: SourcePersonStateContext["status"];
  readonly pages: readonly UnitPeoplePage[];
  readonly error: string | null;
}

const SOURCE_IDLE: SourceState = { key: null, status: "loading", pages: [], error: null };

function sourceKey(locator: PersonStateLocator, limit: number): string {
  return personStateKeys.people(locator, { limit }).join("|");
}

/**
 * 按完整来源 locator 读取本 unit 的人物摘要。切换 unit/catalog 时中止旧请求；
 * 迟到结果按 key 丢弃。`places` 不在此来源 API 契约内，来源页地点状态仍由
 * ReadingContextPanel 的 context_entities 呈现，不伪造一条地点状态。
 */
export function useSourcePersonStateContext(
  locator: PersonStateLocator | null,
  options: { limit?: number; enabled?: boolean } = {},
): SourcePersonStateContext {
  const limit = options.limit ?? 6;
  const enabled = options.enabled ?? true;
  const [state, setState] = useState<SourceState>(SOURCE_IDLE);
  const keyRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const [retryToken, setRetryToken] = useState(0);

  const activeKey = locator ? sourceKey(locator, limit) : null;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!enabled || !locator || !activeKey) {
      keyRef.current = null;
      setState(SOURCE_IDLE);
      return;
    }
    const key = activeKey;
    keyRef.current = key;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ key, status: "loading", pages: [], error: null });
    getReadingPeople(locator, { limit }, { signal: controller.signal })
      .then((page) => {
        if (!mountedRef.current || keyRef.current !== key || controller.signal.aborted) return;
        const empty = (page.people?.length ?? 0) === 0 && page.people_count === 0;
        setState({ key, status: empty ? "empty" : "ready", pages: [page], error: null });
      })
      .catch((error: unknown) => {
        if (!mountedRef.current || keyRef.current !== key || controller.signal.aborted) return;
        if (error instanceof PersonStateAbortError) return;
        const message =
          error instanceof PersonStateApiError
            ? error.message
            : error instanceof Error
              ? error.message
              : String(error);
        setState({ key, status: "error", pages: [], error: message });
      });
    return () => controller.abort();
  }, [activeKey, enabled, limit, retryToken]); // eslint-disable-line react-hooks/exhaustive-deps

  const retry = useCallback(() => {
    setRetryToken((value) => value + 1);
  }, []);

  const loadMorePeople = useCallback(() => {
    const cursor = state.pages[state.pages.length - 1]?.next_cursor;
    if (!locator || !cursor) return;
    const key = state.key;
    getReadingPeople(locator, { limit, cursor })
      .then((page) => {
        if (keyRef.current !== key) return;
        setState((latest) =>
          latest.key === key ? { ...latest, pages: [...latest.pages, page] } : latest,
        );
      })
      .catch(() => {
        /* 保留已取得摘要；用户可重试 */
      });
  }, [locator, limit, state.key, state.pages]);

  const people = useMemo(() => {
    const seen = new Set<string>();
    const merged: PersonSummary[] = [];
    for (const page of state.pages) {
      for (const person of page.people ?? []) {
        if (seen.has(person.person_id)) continue;
        seen.add(person.person_id);
        merged.push(person);
      }
    }
    return merged;
  }, [state.pages]);

  const lastPage = state.pages[state.pages.length - 1] ?? null;

  return {
    key: state.key,
    status: state.status,
    people,
    phases: lastPage?.phases ?? [],
    error: state.error,
    hasMorePeople: Boolean(lastPage?.has_more),
    retry,
    loadMorePeople,
  };
}
