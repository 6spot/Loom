import { useQuery } from "@tanstack/react-query";
import {
  chapterReaderKeys,
  classifyChapterError,
  fetchChapterDirectory,
  type ChapterDirectoryItem,
  type ChapterDirectoryResponse,
} from "../../lib/chapter-reader";

export interface ChapterIndexPageProps {
  initialCursor?: string | null;
  client?: { fetchDirectory: typeof fetchChapterDirectory };
}

/** 篇章目录：已发布阅读版本列表，稳定游标分页。空/加载/404/错误都有明确状态。 */
export default function ChapterIndexPage({
  initialCursor = null,
  client = { fetchDirectory: fetchChapterDirectory },
}: ChapterIndexPageProps) {
  const query = useQuery<ChapterDirectoryResponse>({
    queryKey: chapterReaderKeys.directory({ limit: 50, cursor: initialCursor }),
    queryFn: ({ signal }) =>
      client.fetchDirectory({ limit: 50, cursor: initialCursor }, { signal }),
  });

  if (query.isPending) {
    return (
      <section className="chr-index" data-test="chapter-index-loading" data-view="loading">
        <p className="chr-eyebrow">篇章目录</p>
        <h1>正在读取已发布篇章…</h1>
      </section>
    );
  }
  if (query.isError) {
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
  return <ChapterIndexView data={query.data} />;
}

export function ChapterIndexView({ data }: { data: ChapterDirectoryResponse }) {
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
      </header>
      <ol className="chr-index-list">
        {items.map((item) => (
          <ChapterIndexRow key={item.publication_id} item={item} />
        ))}
      </ol>
      {data.next_cursor ? (
        <p className="chr-muted" data-test="chapter-index-more" data-cursor={data.next_cursor}>
          还有更多篇章，游标 {data.next_cursor.slice(0, 12)}…
        </p>
      ) : null}
    </section>
  );
}

function ChapterIndexRow({ item }: { item: ChapterDirectoryItem }) {
  return (
    <li className="chr-index-row" data-test="chapter-index-row" data-publication={item.publication_id}>
      <span className="chr-index-title">{item.chapter_title ?? item.chapter_id ?? "未命名章节"}</span>
      <span className="chr-muted">{item.source_title ?? item.document_id ?? ""}</span>
      <code className="chr-muted">{item.publication_id}</code>
    </li>
  );
}
