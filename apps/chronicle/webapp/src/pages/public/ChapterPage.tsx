import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import ChapterSourceReference from "../../components/ChapterSourceReference";
import {
  anchorsForBlock,
  canonicalTargetForRef,
  chapterReaderKeys,
  classifyChapterError,
  fetchChapterDetail,
  refDisplayName,
  type ChapterDetailResponse,
  type ChapterTranslationBlock,
} from "../../lib/chapter-reader";

export interface ChapterPageClient {
  fetchDetail: typeof fetchChapterDetail;
}

export interface ChapterPageProps {
  publicationId: string;
  client?: ChapterPageClient;
}

interface OpenSource {
  anchorId: string;
  label: string;
  triggerKey: string;
}

/**
 * 单栏完整白话阅读页。正文单栏优先、章/来源信息次要；全部译文段（含无引用段）
 * 按序渲染；默认无逐句双栏。entity/event refs 只有服务端给出 canonical 目标时
 * 才成为已存在详情页的普通入口，未知或歧义引用如实显示为文本。
 */
export default function ChapterPage({
  publicationId,
  client = { fetchDetail: fetchChapterDetail },
}: ChapterPageProps) {
  const query = useQuery<ChapterDetailResponse>({
    queryKey: chapterReaderKeys.chapter(publicationId),
    queryFn: ({ signal }) => client.fetchDetail(publicationId, { signal }),
  });
  const [openSource, setOpenSource] = useState<OpenSource | null>(null);

  // 切换 publication 时关闭旧引用面板，避免旧 publication 的原文残留。
  useEffect(() => {
    setOpenSource(null);
  }, [publicationId]);

  if (query.isPending) {
    return (
      <section className="chr-reader" data-test="chapter-loading" data-view="loading">
        <p className="chr-eyebrow">篇章阅读</p>
        <h1>正在读取完整白话文…</h1>
        <p className="chr-muted">一次取回整章，不用摘要冒充全文。</p>
      </section>
    );
  }
  if (query.isError) {
    const classified = classifyChapterError(query.error);
    if (classified.kind === "not_found") {
      return (
        <section className="chr-reader" data-test="chapter-not-found" data-view="not-found">
          <p className="chr-eyebrow">404</p>
          <h1>这个阅读版本不存在</h1>
          <p>{classified.message}</p>
          <p className="chr-muted">未发布或跨 publication 的引用不会补读其他版本。</p>
        </section>
      );
    }
    return (
      <section className="chr-reader" data-test="chapter-error" data-view="error" role="alert">
        <p className="chr-eyebrow">{classified.code}</p>
        <h1>正文暂时读不出来</h1>
        <p>{classified.message}</p>
        <button type="button" data-test="chapter-retry" onClick={() => void query.refetch()}>
          重试
        </button>
      </section>
    );
  }
  return <ChapterDetailView detail={query.data} openSource={openSource} onOpenSource={setOpenSource} />;
}

export function ChapterDetailView({
  detail,
  openSource,
  onOpenSource,
}: {
  detail: ChapterDetailResponse;
  openSource?: OpenSource | null;
  onOpenSource?: (source: OpenSource | null) => void;
}) {
  const blocks = useMemo(
    () => (Array.isArray(detail.translation_blocks) ? detail.translation_blocks : []),
    [detail],
  );
  if (blocks.length === 0) {
    return (
      <section className="chr-reader" data-test="chapter-empty" data-view="empty">
        <p className="chr-eyebrow">篇章阅读</p>
        <h1>{detail.chapter_title ?? "未命名章节"}</h1>
        <p>这个阅读版本还没有可显示的完整译文，不会用摘要或其他版本补齐。</p>
      </section>
    );
  }
  return (
    <section
      className="chr-reader"
      data-test="chapter-reader"
      data-publication={detail.publication_id}
      data-blocks={blocks.length}
    >
      <header className="chr-reader-heading">
        <p className="chr-eyebrow">篇章阅读 · 单栏全文</p>
        <h1>{detail.chapter_title ?? "未命名章节"}</h1>
        <p className="chr-meta">
          {[detail.source_title, detail.revision_id ? `版本 ${detail.revision_id}` : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
        <p className="chr-muted">
          全文共 {blocks.length} 段，一次读完；引用默认收起，点击才请求原文。
        </p>
      </header>
      <div className="chr-single-column">
        {blocks.map((block, index) => (
          <TranslationParagraph
            key={block.block_id || `block-${index}`}
            block={block}
            detail={detail}
            position={index + 1}
            onOpenSource={onOpenSource}
          />
        ))}
      </div>
      {openSource ? (
        <ChapterSourceReference
          key={`${detail.publication_id}:${openSource.anchorId}`}
          publicationId={detail.publication_id}
          anchorId={openSource.anchorId}
          anchorLabel={openSource.label}
          onClose={() => onOpenSource?.(null)}
        />
      ) : null}
    </section>
  );
}

function TranslationParagraph({
  block,
  detail,
  position,
  onOpenSource,
}: {
  block: ChapterTranslationBlock;
  detail: ChapterDetailResponse;
  position: number;
  onOpenSource?: (source: OpenSource | null) => void;
}) {
  const anchors = anchorsForBlock(block);
  const entityRefs = Array.isArray(block.entity_refs) ? block.entity_refs : [];
  const eventRefs = Array.isArray(block.event_refs) ? block.event_refs : [];
  return (
    <article className="chr-paragraph" data-test="chapter-paragraph" data-block={block.block_id}>
      <p className="chr-paragraph-text">{block.text}</p>
      <div className="chr-paragraph-meta">
        <span className="chr-position">第 {position} 段</span>
        {anchors.map((anchorId) => (
          <button
            key={anchorId}
            type="button"
            className="chr-source-button"
            data-test="chapter-source-open"
            data-anchor={anchorId}
            onClick={() =>
              onOpenSource?.({ anchorId, label: `第 ${position} 段 · ${anchorId}`, triggerKey: block.block_id })
            }
          >
            看原文 {anchorId.slice(0, 12)}
          </button>
        ))}
        {anchors.length === 0 ? (
          <span className="chr-muted" data-test="chapter-source-unavailable">
            本段暂无服务端下发的原文锚点
          </span>
        ) : null}
        <span className="chr-refs">
          {entityRefs.map((ref, index) => {
            const target = canonicalTargetForRef(ref, detail.references);
            const label = refDisplayName(ref, detail.references);
            return target ? (
              <a key={`${ref.ref}:${index}`} className="chr-ref-link" href={target} data-test="chapter-entity-link">
                {label}
              </a>
            ) : (
              <span key={`${ref.ref}:${index}`} className="chr-ref-text" data-test="chapter-entity-text" title={`${ref.kind}:${ref.ref}`}>
                {label}
              </span>
            );
          })}
          {eventRefs.map((ref, index) => {
            const target = canonicalTargetForRef(ref, detail.references);
            const label = refDisplayName(ref, detail.references);
            return target ? (
              <a key={`${ref.ref}:${index}`} className="chr-ref-link" href={target} data-test="chapter-event-link">
                {label}
              </a>
            ) : (
              <span key={`${ref.ref}:${index}`} className="chr-ref-text" data-test="chapter-event-text" title={`${ref.kind}:${ref.ref}`}>
                {label}
              </span>
            );
          })}
        </span>
      </div>
    </article>
  );
}
