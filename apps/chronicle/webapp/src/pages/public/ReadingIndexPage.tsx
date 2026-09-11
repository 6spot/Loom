// C2-R2-T15 连续阅读目录页（`/read`）。
//
// 公开目录列出已发布的阅读 stream，并使用服务端返回的 snapshot 固定探索范围：
// 首屏不带 catalog，服务端解析一次最新 publication_sequence；之后翻页与进入正文
// 都显式携带同一 catalog。目录只负责导航，不内联正文，也不切换叙事时间。

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchReadingStreams,
  readingKeys,
  ReadingApiError,
  type ReadingDirectoryEnvelope,
  type ReadingStreamDirectoryItem,
} from "../../lib/reading-api";
import { readingPath } from "../../lib/routes";

export interface ReadingIndexPageClient {
  fetchDirectory: typeof fetchReadingStreams;
}

export interface ReadingIndexPageProps {
  client?: ReadingIndexPageClient;
  /** 选中 stream 回调；缺省渲染为指向 `/read/{stream}?catalog=` 的链接。 */
  onSelectStream?: (item: ReadingStreamDirectoryItem, catalogSha: string) => void;
  hrefForStream?: (streamId: string, catalogSha: string) => string;
}

function errorCode(error: unknown): string {
  return error instanceof ReadingApiError ? error.code : "unknown_error";
}

function errorMessage(error: unknown): string {
  return error instanceof ReadingApiError ? error.message : "阅读目录暂时不可用，请稍后重试";
}

/** 连续阅读目录：稳定游标分页、固定 catalog，空/加载/错误都有明确状态。 */
export default function ReadingIndexPage({
  client = { fetchDirectory: fetchReadingStreams },
  onSelectStream,
  hrefForStream,
}: ReadingIndexPageProps) {
  const [cursor, setCursor] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<string | null>(null);
  const [items, setItems] = useState<ReadingStreamDirectoryItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  const query = useQuery<ReadingDirectoryEnvelope, unknown>({
    queryKey: readingKeys.directory({ catalog, limit: 20, cursor }),
    queryFn: ({ signal }) => client.fetchDirectory({ catalog, limit: 20, cursor }, { signal }),
  });

  useEffect(() => {
    const envelope = query.data;
    if (!envelope) return;
    if (!catalog) setCatalog(envelope.snapshot.catalog_sha);
    setItems((previous) => {
      const seen = new Set(previous.map((item) => item.stream_id));
      const merged = [...previous];
      for (const item of envelope.page.streams ?? []) {
        if (!item || seen.has(item.stream_id)) continue;
        seen.add(item.stream_id);
        merged.push(item);
      }
      return merged;
    });
    setNextCursor(envelope.page.next_cursor);
  }, [query.data, catalog]);

  if (query.isPending && items.length === 0) {
    return (
      <section className="rpage-index" data-test="reading-index-loading" data-view="loading">
        <p className="rpage-eyebrow">连续阅读</p>
        <h1>正在读取已发布正文…</h1>
      </section>
    );
  }
  if (query.isError && items.length === 0) {
    return (
      <section className="rpage-index" data-test="reading-index-error" data-view="error" role="alert">
        <p className="rpage-eyebrow">{errorCode(query.error)}</p>
        <h1>目录暂时读不出来</h1>
        <p>{errorMessage(query.error)}</p>
        <button type="button" data-test="reading-index-retry" onClick={() => void query.refetch()}>
          重试
        </button>
      </section>
    );
  }

  if (items.length === 0) {
    return (
      <section className="rpage-index" data-test="reading-index-empty" data-view="empty">
        <p className="rpage-eyebrow">连续阅读</p>
        <h1>还没有已发布的连续正文</h1>
        <p className="rpage-muted">未发布的内容不会出现在这里。</p>
      </section>
    );
  }

  const resolvedCatalog = catalog ?? "";
  return (
    <section
      className="rpage-index"
      data-test="reading-index"
      data-count={items.length}
      data-catalog={resolvedCatalog}
    >
      <header className="rpage-index-heading">
        <p className="rpage-eyebrow">连续阅读</p>
        <h1>已发布正文</h1>
        <p className="rpage-muted">
          每条正文固定一个不可变版本；探索快照 <code>{resolvedCatalog.slice(0, 12)}…</code>
        </p>
      </header>
      <ol className="rpage-index-list">
        {items.map((item) => (
          <ReadingIndexRow
            key={item.stream_id}
            item={item}
            catalogSha={resolvedCatalog}
            onSelectStream={onSelectStream}
            hrefForStream={hrefForStream}
          />
        ))}
      </ol>
      {nextCursor || query.isError ? (
        <div className="rpage-index-more">
          {query.isError ? (
            <div className="rpage-state-card" data-test="reading-index-page-error" role="alert">
              <p className="rpage-eyebrow">{errorCode(query.error)}</p>
              <p>下一页暂时读不出来，已加载的正文不受影响。</p>
              <p className="rpage-muted">{errorMessage(query.error)}</p>
            </div>
          ) : null}
          <button
            type="button"
            className="rpage-load-more"
            data-test="reading-index-more-button"
            disabled={query.isFetching}
            onClick={() => {
              if (query.isError) void query.refetch();
              else if (nextCursor) setCursor(nextCursor);
            }}
          >
            {query.isFetching ? "正在读下一页…" : query.isError ? "重试读下一页" : "读下一页"}
          </button>
        </div>
      ) : (
        <p className="rpage-muted" data-test="reading-index-end">目录已读完。</p>
      )}
    </section>
  );
}

function ReadingIndexRow({
  item,
  catalogSha,
  onSelectStream,
  hrefForStream,
}: {
  item: ReadingStreamDirectoryItem;
  catalogSha: string;
  onSelectStream?: (item: ReadingStreamDirectoryItem, catalogSha: string) => void;
  hrefForStream?: (streamId: string, catalogSha: string) => string;
}) {
  const title = item.document_id ?? item.stream_id;
  const href = (hrefForStream ?? readingPath)(item.stream_id, catalogSha);
  return (
    <li className="rpage-index-row" data-test="reading-index-row" data-stream={item.stream_id}>
      <a
        className="rpage-index-title"
        data-test="reading-index-open"
        data-stream={item.stream_id}
        href={href}
        onClick={(event) => {
          if (!onSelectStream) return;
          event.preventDefault();
          onSelectStream(item, catalogSha);
        }}
      >
        {title}
      </a>
      <span className="rpage-muted">
        第 {item.revision_no} 版 · {item.unit_count} 段 · {item.group_count} 个时间区段
      </span>
    </li>
  );
}
