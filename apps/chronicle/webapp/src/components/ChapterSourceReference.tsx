import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChapterReaderApiError,
  chapterSourcePath,
  chapterReaderKeys,
  classifyChapterError,
  createStaleGuard,
  fetchChapterSource,
  type ChapterSourceResponse,
  type ChapterSourceView,
} from "../lib/chapter-reader";

export interface ChapterSourceClient {
  fetchSource: typeof fetchChapterSource;
}

const defaultClient: ChapterSourceClient = { fetchSource: fetchChapterSource };

export interface ChapterSourceReferenceProps {
  publicationId: string;
  anchorId: string;
  /** 触发本次展开的按钮 label（用于无障碍与关闭恢复焦点）。 */
  anchorLabel?: string;
  initialView?: ChapterSourceView;
  client?: ChapterSourceClient;
  /** 关闭时恢复焦点到触发元素；调用方也可自行处理。 */
  onClose?: () => void;
}

/**
 * 按需原文引用面板。点击引用后才请求原文；支持 window→整章展开与续页；
 * 关闭时恢复触发焦点与阅读位置（不自动跳顶）；失败保留已读内容并允许重试。
 * 正文一律按普通文本渲染（React 自动转义），高亮完全使用服务端切好的 segments。
 */
export default function ChapterSourceReference({
  publicationId,
  anchorId,
  anchorLabel,
  initialView = "window",
  client = defaultClient,
  onClose,
}: ChapterSourceReferenceProps) {
  const [view, setView] = useState<ChapterSourceView>(initialView);
  const [cursor, setCursor] = useState<string | null>(null);
  const [pages, setPages] = useState<ChapterSourceResponse[]>([]);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const guardRef = useRef(createStaleGuard());
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<Element | null>(null);
  const scrollRef = useRef(0);

  useEffect(() => {
    triggerRef.current = document.activeElement;
    scrollRef.current = window.scrollY;
    closeButtonRef.current?.focus();
    return () => {
      // 关闭恢复触发焦点；浏览器会把阅读位置带回触发点附近，不主动 scrollTo(0)。
      const trigger = triggerRef.current;
      if (trigger instanceof HTMLElement) trigger.focus({ preventScroll: false });
      else if (typeof scrollRef.current === "number") window.scrollTo({ top: scrollRef.current });
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose?.();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const load = useCallback(
    async (nextView: ChapterSourceView, nextCursor: string | null, append: boolean) => {
      const token = guardRef.current.next();
      setPending(true);
      setError(null);
      try {
        const page = await client.fetchSource(publicationId, anchorId, {
          view: nextView,
          cursor: nextCursor,
        });
        if (!guardRef.current.isCurrent(token)) return; // 迟到响应丢弃，不覆盖当前视图
        setPages((previous) => (append ? [...previous, page] : [page]));
        setCursor(page.next_cursor);
      } catch (failure) {
        if (!guardRef.current.isCurrent(token)) return;
        const classified = classifyChapterError(failure);
        setError({
          code:
            failure instanceof ChapterReaderApiError
              ? failure.code
              : classified.code,
          message: classified.message,
        });
      } finally {
        if (guardRef.current.isCurrent(token)) setPending(false);
      }
    },
    [client, publicationId, anchorId],
  );

  useEffect(() => {
    setPages([]);
    setCursor(null);
    void load(view, null, false);
  }, [publicationId, anchorId, view, load]);

  const queryKey = chapterReaderKeys.source(publicationId, anchorId, { view, cursor });
  const retry = () => {
    void load(view, pages.length ? cursor : null, pages.length > 0);
  };

  return (
    <section
      className="chr-source-panel"
      data-test="chapter-source-panel"
      data-publication={publicationId}
      data-anchor={anchorId}
      data-view={view}
      data-query-key={JSON.stringify(queryKey)}
      aria-label={anchorLabel ? `原文引用：${anchorLabel}` : "原文引用"}
    >
      <header className="chr-source-heading">
        <div>
          <p className="chr-eyebrow">原文依据 · 按需加载</p>
          <h3>{anchorLabel ?? anchorId}</h3>
          <p className="chr-muted">请求 {chapterSourcePath(publicationId, anchorId, { view })}，只读，不触发模型。</p>
        </div>
        <button
          ref={closeButtonRef}
          type="button"
          className="chr-close-button"
          data-test="chapter-source-close"
          onClick={onClose}
        >
          关闭并回到正文
        </button>
      </header>

      <div className="chr-source-toolbar" role="group" aria-label="原文视图切换">
        <button
          type="button"
          data-test="chapter-source-view-window"
          aria-pressed={view === "window"}
          disabled={pending && pages.length === 0}
          onClick={() => setView("window")}
        >
          片段＋前后文
        </button>
        <button
          type="button"
          data-test="chapter-source-view-chapter"
          aria-pressed={view === "chapter"}
          disabled={pending && pages.length === 0}
          onClick={() => setView("chapter")}
        >
          展开整章
        </button>
      </div>

      {error && pages.length === 0 ? (
        <div className="chr-state-card" data-test="chapter-source-error" role="alert">
          <p className="chr-eyebrow">{error.code}</p>
          <p>原文暂时读不出来，正文不受影响。</p>
          <p className="chr-muted">{error.message}</p>
          <button type="button" data-test="chapter-source-retry" onClick={retry}>
            重试
          </button>
        </div>
      ) : null}

      {pending && pages.length === 0 && !error ? (
        <p className="chr-muted" data-test="chapter-source-loading">正在读取原文…</p>
      ) : null}

      {pages.map((page, pageIndex) => (
        <SourcePageSegments key={`${page.anchor_id}:${pageIndex}`} page={page} />
      ))}

      {error && pages.length > 0 ? (
        <div className="chr-state-card" data-test="chapter-source-page-error" role="alert">
          <p className="chr-muted">续页失败，已保留已读原文：{error.message}</p>
          <button type="button" data-test="chapter-source-retry" onClick={retry}>
            重试续页
          </button>
        </div>
      ) : null}

      <div className="chr-source-footer">
        {pending && pages.length > 0 ? <p className="chr-muted">正在读取更多原文…</p> : null}
        {!pending && pages.length > 0 && cursor ? (
          <button type="button" data-test="chapter-source-more" onClick={() => void load(view, cursor, true)}>
            继续读下一页
          </button>
        ) : null}
        {!pending && pages.length > 0 && !cursor ? (
          <p className="chr-muted" data-test="chapter-source-end">本视图已读完。</p>
        ) : null}
      </div>
    </section>
  );
}

export function SourcePageSegments({ page }: { page: ChapterSourceResponse }) {
  if (!page.segments || page.segments.length === 0) {
    return <p className="chr-muted">服务端未返回原文片段（anchor 有记录但无可用文本）。</p>;
  }
  return (
    <div className="chr-source-text" data-test="chapter-source-segments">
      {page.segments.map((segment, index) =>
        segment.highlight ? (
          <mark key={index} data-test="chapter-source-hit">{segment.text}</mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </div>
  );
}
