// C2-R2-T10 content suite 的受控窗口封装（仅测试使用，不进生产构建）。
//
// 把生产 ReadingWindow 接到受控的相邻/跨章/大页/远页响应与 mock 原文 client 上，
// 提供操作入口供 content.mjs 浏览器验证。这里不复制窗口逻辑：页合并、去重、
// 有界回收、占位与固定单位都由生产组件负责。

import { useCallback, useMemo, useState } from "react";
import ReadingWindow, {
  type ReadingWindowError,
} from "../../../../../src/components/reading/ReadingWindow";
import type { ChapterSourceResponse } from "../../../../../src/lib/chapter-reader";
import type { ChapterSourceClient } from "../../../../../src/components/ChapterSourceReference";
import type { ReadingDirection, StreamPage } from "../../../../../src/lib/reading-types";
import {
  BULK_PAGE,
  FAR_PAGE,
  INITIAL_PAGE,
  NEXT_PAGE,
  PREVIOUS_PAGE,
  pageOf,
} from "./fixtures";

type LoadMode = "ok" | "fail" | "blank" | "late";

const LATE_DELAY_MS = 600;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function sourcePage(anchorId: string, view: "window" | "chapter", cursor: string | null): ChapterSourceResponse {
  const longQuote =
    "合成原文：此处用于验证长原文按需展开、分页与关闭回到触发点，不冒充任何真实史料文本。";
  if (view === "window") {
    return {
      anchor_id: anchorId,
      view,
      source_sha256: "d".repeat(64),
      chapter_range: [0, 2],
      page_range: [0, 0],
      segments: [{ text: longQuote, highlight: true }],
      next_cursor: null,
      has_more: false,
    };
  }
  if (cursor === "src-page-2") {
    return {
      anchor_id: anchorId,
      view,
      source_sha256: "d".repeat(64),
      chapter_range: [0, 6],
      page_range: [4, 5],
      segments: [{ text: `续页：${longQuote}` }],
      next_cursor: null,
      has_more: false,
    };
  }
  return {
    anchor_id: anchorId,
    view,
    source_sha256: "d".repeat(64),
    chapter_range: [0, 6],
    page_range: [0, 3],
    segments: [{ text: longQuote }, { text: `片段二：${longQuote}`, highlight: true }],
    next_cursor: "src-page-2",
    has_more: true,
  };
}

const sourceClient: ChapterSourceClient = {
  fetchSource: (publicationId: string, anchorId: string, query = {}) => {
    return Promise.resolve(sourcePage(anchorId, query.view ?? "window", query.cursor ?? null));
  },
};

export function ControlledContentWindow() {
  const [pages, setPages] = useState<StreamPage[]>([INITIAL_PAGE]);
  const [activeUnitId, setActiveUnitId] = useState<string | null>(
    INITIAL_PAGE.units[0]?.unit_id ?? null,
  );
  const [loadingDirection, setLoadingDirection] = useState<ReadingDirection | null>(null);
  const [error, setError] = useState<ReadingWindowError | null>(null);
  const [mode, setMode] = useState<LoadMode>("ok");
  const [loads, setLoads] = useState(0);
  const [sourceFails, setSourceFails] = useState(false);

  const activeSourceClient = useMemo<ChapterSourceClient>(
    () =>
      sourceFails
        ? {
            fetchSource: () => Promise.reject(new Error("source_missing")),
          }
        : sourceClient,
    [sourceFails],
  );

  const performLoad = useCallback(
    async (direction: ReadingDirection, loadMode: LoadMode) => {
      setLoadingDirection(direction);
      setError(null);
      try {
        if (loadMode === "fail") throw new Error("content controlled failure: upstream_limited");
        if (loadMode === "late") await delay(LATE_DELAY_MS);
        if (loadMode === "blank") {
          setPages((previous) => [...previous, pageOf([], { hasNext: false })]);
          return;
        }
        const page = direction === "previous" ? PREVIOUS_PAGE : NEXT_PAGE;
        setPages((previous) => [...previous, page]);
      } catch (failure) {
        setError({
          message: failure instanceof Error ? failure.message : String(failure),
          direction,
        });
      } finally {
        setLoadingDirection(null);
        setLoads((count) => count + 1);
      }
    },
    [],
  );

  const requestPage = useCallback(
    (direction: ReadingDirection) => {
      void performLoad(direction, mode);
    },
    [mode, performLoad],
  );

  const onRetry = useCallback(() => {
    void performLoad("next", "ok");
  }, [performLoad]);

  const activeOrdinal = useMemo(() => {
    for (const page of pages) {
      const unit = page.units.find((candidate) => candidate.unit_id === activeUnitId);
      if (unit) return unit.ordinal;
    }
    return -1;
  }, [pages, activeUnitId]);

  const advanceActive = useCallback(() => {
    const merged = pages.flatMap((page) => page.units).sort((a, b) => a.ordinal - b.ordinal);
    const index = merged.findIndex((unit) => unit.unit_id === activeUnitId);
    const next = merged[Math.min(index + 1, merged.length - 1)];
    if (next) setActiveUnitId(next.unit_id);
  }, [pages, activeUnitId]);

  const jumpFar = useCallback(() => {
    setPages([FAR_PAGE]);
    setActiveUnitId(FAR_PAGE.units[20]?.unit_id ?? null);
    setError(null);
  }, []);

  const loadBulk = useCallback(() => {
    setPages((previous) => [...previous, BULK_PAGE]);
  }, []);

  const reset = useCallback(() => {
    setPages([INITIAL_PAGE]);
    setActiveUnitId(INITIAL_PAGE.units[0]?.unit_id ?? null);
    setError(null);
  }, []);

  const setLargeFont = useCallback(() => {
    document.documentElement.style.fontSize = "32px";
  }, []);

  const setNormalFont = useCallback(() => {
    document.documentElement.style.fontSize = "16px";
  }, []);

  return (
    <main className="rcw-scene" data-test="content-scene" data-synthetic="true">
      <p data-test="content-synthetic-note">
        合成 fixture：受控相邻/跨章/大页/远页与 mock 原文，仅验证组件行为，不是真实后端或模型输出。
      </p>

      <section className="rcw-scene-toolbar" data-test="content-controls" aria-label="content 场景控制">
        <span data-test="content-mode">{mode}</span>
        <span data-test="content-loaded-pages">{loads}</span>
        <span data-test="content-active-ordinal">{activeOrdinal}</span>
        <button type="button" data-test="content-load-next-ok" onClick={() => void performLoad("next", "ok")}>
          下一页
        </button>
        <button type="button" data-test="content-load-prev-ok" onClick={() => void performLoad("previous", "ok")}>
          上一页
        </button>
        <button type="button" data-test="content-load-next-fail" onClick={() => void performLoad("next", "fail")}>
          下一页·受控失败
        </button>
        <button type="button" data-test="content-load-next-blank" onClick={() => void performLoad("next", "blank")}>
          下一页·空白
        </button>
        <button type="button" data-test="content-load-next-late" onClick={() => void performLoad("next", "late")}>
          下一页·受控迟到
        </button>
        <button type="button" data-test="content-load-bulk" onClick={loadBulk}>
          载入大批正文
        </button>
        <button type="button" data-test="content-jump-far" onClick={jumpFar}>
          跳到远处目标
        </button>
        <button type="button" data-test="content-active-next" onClick={advanceActive}>
          下一段
        </button>
        <button type="button" data-test="content-font-large" onClick={setLargeFont}>
          200% 字号
        </button>
        <button type="button" data-test="content-font-normal" onClick={setNormalFont}>
          恢复字号
        </button>
        <button type="button" data-test="content-reset" onClick={reset}>
          重置
        </button>
        <label>
          模式
          <select
            data-test="content-mode-select"
            value={mode}
            onChange={(event) => setMode(event.target.value as LoadMode)}
          >
            <option value="ok">ok</option>
            <option value="fail">fail</option>
            <option value="blank">blank</option>
            <option value="late">late</option>
          </select>
        </label>
        <label>
          原文失败
          <input
            type="checkbox"
            data-test="content-source-fail"
            checked={sourceFails}
            onChange={(event) => setSourceFails(event.target.checked)}
          />
        </label>
      </section>

      <ReadingWindow
        pages={pages}
        activeUnitId={activeUnitId}
        chapterTitles={{ "chap-a": "卷一 · 吴书", "chap-b": "卷二 · 魏书" }}
        loadingDirection={loadingDirection}
        error={error}
        callbacks={{ requestPage, onRetry }}
        sourceClient={activeSourceClient}
      />
    </main>
  );
}
