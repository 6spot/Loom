import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  chapterReaderKeys,
  classifyChapterError,
  fetchChapterDirectory,
  mergeDirectoryPages,
  type ChapterDirectoryItem,
  type ChapterDirectoryResponse,
} from "../../lib/chapter-reader";

export interface ChapterIndexPageProps {
  initialCursor?: string | null;
  client?: { fetchDirectory: typeof fetchChapterDirectory };
  /** 选中章节回调（目录 → 单栏完整白话的导航入口，不经过 App/router，T17 再接路由）。 */
  onSelectChapter?: (publicationId: string) => void;
  /** 明确外部 href 映射时渲染为链接；缺省渲染为按钮并走 onSelectChapter。 */
  hrefForPublicationId?: (publicationId: string) => string;
}

/** 篇章目录：已发布阅读版本列表，稳定游标分页，可进入章节。空/加载/404/错误都有明确状态。 */
export default function ChapterIndexPage({
  initialCursor = null,
  client = { fetchDirectory: fetchChapterDirectory },
  onSelectChapter,
  hrefForPublicationId,
}: ChapterIndexPageProps) {
  const [cursor, setCursor] = useState<string | null>(initialCursor);
  const [items, setItems] = useState<ChapterDirectoryItem[]>([]);
  // 最近一次成功页的 next_cursor：后续页失败时 query.data 为空，仍以此为准，
  // 绝不把分页失败误报为“目录已读完”。
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const query = useQuery<ChapterDirectoryResponse>({
    queryKey: chapterReaderKeys.directory({ limit: 50, cursor }),
    queryFn: ({ signal }) => client.fetchDirectory({ limit: 50, cursor }, { signal }),
  });

  useEffect(() => {
    setCursor(initialCursor);
    setItems([]);
    setNextCursor(null);
  }, [initialCursor]);

  useEffect(() => {
    if (query.data) {
      setItems((previous) => mergeDirectoryPages(previous, query.data as ChapterDirectoryResponse));
      setNextCursor((query.data as ChapterDirectoryResponse).next_cursor);
    }
  }, [query.data]);

  if (query.isPending && items.length === 0) {
    return (
      <section className="chr-index" data-test="chapter-index-loading" data-view="loading">
        <p className="chr-eyebrow">篇章目录</p>
        <h1>正在读取已发布篇章…</h1>
      </section>
    );
  }
  if (query.isError && items.length === 0) {
    const classified = classifyChapterError(query.error);
    return (
      <section className="chr-index" data-test="chapter-index-error" data-view="error" role="alert">
        <p className="chr-eyebrow">{classified.code}</p>
        <h1>目录暂时读不出来</h1>
        <p>{classified.message}</p>
        <button type="button" data-test="chapter-index-retry" onClick={() => void query.refetch()}>
          重试
        </button>
      </section>
    );
  }
  // 后续页失败：保留已加载条目，行内报错并允许重试同一游标，不报“已读完”。
  const pageError = query.isError && items.length > 0 ? classifyChapterError(query.error) : null;
  return (
    <ChapterIndexView
      data={{ items, next_cursor: nextCursor }}
      loadingMore={query.isFetching}
      pageError={pageError}
      onLoadMore={() => {
        if (pageError) {
          void query.refetch();
          return;
        }
        if (nextCursor) setCursor(nextCursor);
      }}
      onSelectChapter={onSelectChapter}
      hrefForPublicationId={hrefForPublicationId}
    />
  );
}

export function ChapterIndexView({
  data,
  loadingMore = false,
  pageError = null,
  onLoadMore,
  onSelectChapter,
  hrefForPublicationId,
}: {
  data: ChapterDirectoryResponse;
  loadingMore?: boolean;
  pageError?: { code: string; message: string } | null;
  onLoadMore?: () => void;
  onSelectChapter?: (publicationId: string) => void;
  hrefForPublicationId?: (publicationId: string) => string;
}) {
  const items = Array.isArray(data.items) ? data.items : [];
  if (items.length === 0) {
    return (
      <section className="chr-index" data-test="chapter-index-empty" data-view="empty">
        <p className="chr-eyebrow">篇章目录</p>
        <h1>还没有已发布的篇章</h1>
        <p className="chr-muted">未发布的内容不会出现在这里。</p>
      </section>
    );
  }
  return (
    <section className="chr-index" data-test="chapter-index" data-count={items.length}>
      <header>
        <p className="chr-eyebrow">篇章目录</p>
        <h1>已发布篇章</h1>
        <p className="chr-muted">每个条目都是不可变的阅读版本（publication_id）。</p>
        <p className="chr-muted">
          连续阅读完整正文：
          <a
            className="chr-ref-link"
            data-test="chapter-index-reading"
            href="/read"
            style={{ marginLeft: "0.35rem" }}
          >
            进入连续阅读目录
          </a>
        </p>
      </header>
      <ol className="chr-index-list">
        {items.map((item) => (
          <ChapterIndexRow
            key={item.publication_id}
            item={item}
            onSelectChapter={onSelectChapter}
            hrefForPublicationId={hrefForPublicationId}
          />
        ))}
      </ol>
      {data.next_cursor || onLoadMore || pageError ? (
        <div className="chr-index-more">
          {data.next_cursor && !pageError ? (
            <p className="chr-muted" data-test="chapter-index-more" data-cursor={data.next_cursor}>
              还有更多篇章，游标 {data.next_cursor.slice(0, 12)}…
            </p>
          ) : null}
          {pageError ? (
            <div className="chr-state-card" data-test="chapter-index-page-error" role="alert">
              <p className="chr-eyebrow">{pageError.code}</p>
              <p>下一页暂时读不出来，已加载的篇章不受影响。</p>
              <p className="chr-muted">{pageError.message}</p>
            </div>
          ) : null}
          {onLoadMore && (data.next_cursor || pageError) ? (
            <button
              type="button"
              data-test="chapter-index-more-button"
              disabled={loadingMore}
              onClick={onLoadMore}
            >
              {loadingMore ? "正在读下一页…" : pageError ? "重试读下一页" : "读下一页"}
            </button>
          ) : null}
          {!data.next_cursor && !pageError && !loadingMore ? (
            <p className="chr-muted" data-test="chapter-index-end">目录已读完。</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function ChapterIndexRow({
  item,
  onSelectChapter,
  hrefForPublicationId,
}: {
  item: ChapterDirectoryItem;
  onSelectChapter?: (publicationId: string) => void;
  hrefForPublicationId?: (publicationId: string) => string;
}) {
  const title = item.chapter_title ?? item.chapter_id ?? "未命名章节";
  const href = hrefForPublicationId?.(item.publication_id);
  return (
    <li className="chr-index-row" data-test="chapter-index-row" data-publication={item.publication_id}>
      {href ? (
        <a
          className="chr-index-title chr-index-link"
          data-test="chapter-index-open"
          data-publication={item.publication_id}
          href={href}
          onClick={(event) => {
            if (!onSelectChapter) return;
            event.preventDefault();
            onSelectChapter(item.publication_id);
          }}
        >
          {title}
        </a>
      ) : (
        <button
          type="button"
          className="chr-index-title chr-index-link"
          data-test="chapter-index-open"
          data-publication={item.publication_id}
          onClick={() => onSelectChapter?.(item.publication_id)}
        >
          {title}
        </button>
      )}
      <span className="chr-muted">{item.source_title ?? item.document_id ?? ""}</span>
      <code className="chr-muted">{item.publication_id}</code>
    </li>
  );
}
