import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import ReadingTargetPicker from "./reading/ReadingTargetPicker";
import { readPath, readingPath } from "../lib/routes";
import { buildReadingUrl } from "../lib/reading-location";
import { fetchReadingStreams, loadReadingEventTargets } from "../lib/reading-api";
import type { EventTarget, EventTargetPage, ReadingLocator } from "../lib/reading-types";

/**
 * 合并事件目标分页：按 (span_id, unit_id) 去重追加，游标与计数以最新页为准。
 * 纯函数，保证 EventPage 与事件预览卡使用同一份“分页不能把首批当全部”的语义。
 */
export function mergeEventTargetPages(
  current: EventTargetPage | null,
  next: EventTargetPage,
): EventTargetPage {
  if (!current) return next;
  const seen = new Set(current.targets.map((target) => `${target.span_id}:${target.unit_id}`));
  const merged = [...current.targets];
  for (const target of next.targets ?? []) {
    const key = `${target.span_id}:${target.unit_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(target);
  }
  return {
    ...next,
    targets: merged,
  };
}

/**
 * 事件详情 → 连续正文入口。优先恢复阅读返回 token；没有 token 时显示目录入口，
 * 并在已知 catalog 时列出该事件的精确正文位置（current/mention 分开）。
 * targets 为游标分页：首批之后由用户显式「加载更多位置」继续取，绝不把首批当全部。
 */
type EventReadingEntryProps = {
  eventId: string;
  catalog: string | null;
  returnLocator: ReadingLocator | null;
  anchor?: boolean;
};

export default function EventReadingEntry(props: EventReadingEntryProps) {
  return <PinnedEventReadingEntry key={`${props.eventId}:${props.catalog ?? "latest"}`} {...props} />;
}

function PinnedEventReadingEntry({
  eventId,
  catalog,
  returnLocator,
  anchor = false,
}: EventReadingEntryProps) {
  const navigate = useNavigate();
  const [catalogSha, setCatalogSha] = useState<string | null>(catalog);
  const [targets, setTargets] = useState<EventTargetPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);
  const moreSeqRef = useRef(0);
  const jumpedRef = useRef(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (catalogSha || !eventId) return;
    let cancelled = false;
    fetchReadingStreams({ limit: 1 })
      .then((envelope) => {
        if (!cancelled) setCatalogSha(envelope.snapshot.catalog_sha);
      })
      .catch(() => {
        if (!cancelled) setError("阅读位置暂时无法载入，请重试。");
      });
    return () => {
      cancelled = true;
      moreSeqRef.current += 1;
    };
  }, [catalogSha, eventId, attempt]);

  useEffect(() => {
    if (!catalogSha) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setTargets(null);
    setLoadingMore(false);
    setMoreError(null);
    moreSeqRef.current += 1;
    loadReadingEventTargets(eventId, { catalog: catalogSha, limit: 20 })
      .then((page) => {
        if (!cancelled) setTargets(page);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "正文位置暂时读不出来");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [catalogSha, eventId, attempt]);

  useEffect(() => {
    if (!anchor || !targets || jumpedRef.current) return;
    const candidates = targets.targets.filter((target) => target.relation === "current");
    if (targets.current_count === 1 && candidates.length === 1) {
      jumpedRef.current = true;
      navigate(buildReadingUrl(candidates[0].locator));
    }
  }, [anchor, targets, navigate]);

  const loadMore = () => {
    const cursor = targets?.next_cursor;
    if (!catalogSha || !cursor || loadingMore) return;
    moreSeqRef.current += 1;
    const token = moreSeqRef.current;
    setLoadingMore(true);
    setMoreError(null);
    loadReadingEventTargets(eventId, { catalog: catalogSha, cursor, limit: 20 })
      .then((page) => {
        if (moreSeqRef.current !== token) return;
        setTargets((current) => mergeEventTargetPages(current, page));
      })
      .catch((cause: unknown) => {
        if (moreSeqRef.current === token) {
          setMoreError(cause instanceof Error ? cause.message : "更多位置暂时读不出来");
        }
      })
      .finally(() => {
        if (moreSeqRef.current === token) setLoadingMore(false);
      });
  };

  const choose = (target: EventTarget) => {
    if (!catalogSha) return;
    navigate(readingPath(target.stream_id, catalogSha, target.unit_id));
  };

  return (
    <section className={anchor ? "reading-entry reading-entry-anchor" : "panel reading-entry"} data-test="event-reading-entry">
      {!anchor ? <div className="panel-heading"><h2>进入相关正文</h2></div> : null}
      {!anchor && (returnLocator ? (
        <Link className="primary-link" data-test="reading-return" to={buildReadingUrl(returnLocator)}>
          返回阅读
        </Link>
      ) : (
        <Link className="primary-link" data-test="reading-enter-directory" to={readPath()}>
          选择阅读位置
        </Link>
      ))}
      {(loading || (!catalogSha && !error)) ? <p className="muted" data-test="event-reading-loading">正在读取正文位置…</p> : null}
      {error ? (
        <div role="alert"><p className="muted" data-test="event-reading-error">{error}</p><button className="public-text-button" type="button" onClick={() => { setError(null); setAttempt((value) => value + 1); }}>重试</button></div>
      ) : null}
      {targets && targets.targets.length > 0 ? (
        <ReadingTargetPicker
          mode={anchor ? "locate" : "other"}
          targets={targets.targets}
          currentCount={targets.current_count}
          mentionCount={targets.mention_count}
          onChoose={choose}
          hasMore={targets.has_more}
          loadingMore={loadingMore}
          onLoadMore={loadMore}
        />
      ) : null}
      {moreError ? (
        <p className="muted" data-test="event-reading-more-error" role="alert">
          {moreError}
        </p>
      ) : null}
      {targets && targets.targets.length === 0 && !loading ? (
        <p className="muted" data-test="event-reading-empty">这段历史的正文还没有发布。</p>
      ) : null}
    </section>
  );
}
