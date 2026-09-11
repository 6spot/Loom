// C2-R2-T10 连续正文的单个 unit 内容渲染（正文优先，无卡片墙）。
//
// 只渲染服务端已切好的 segments（React 默认转义，绝不 replace/innerHTML），
// 章标题只在真实章边界出现；事件词渲染交给 T13 的 renderEvent slot；
// 原文引用默认复用第一轮 ChapterSourceReference，按需展开并保持原 publication。
// 组件不发模型请求、不拥有路由/历史、不自行选择 active unit。

import { Fragment, type ReactNode } from "react";
import ChapterSourceReference, {
  type ChapterSourceClient,
} from "../ChapterSourceReference";
import {
  type ReadingEventSegment,
  type ReadingUnit,
} from "../../lib/reading-types";

export interface ReadingEventSlot {
  readonly segment: ReadingEventSegment;
  readonly unit: ReadingUnit;
}

export type ReadingEventRenderer = (slot: ReadingEventSlot) => ReactNode;

export interface ReadingSourceSlot {
  readonly unit: ReadingUnit;
  readonly anchorId: string;
  readonly anchorLabel: string;
  readonly onClose: () => void;
}

export type ReadingSourceRenderer = (slot: ReadingSourceSlot) => ReactNode;

export interface ReadingContentProps {
  readonly unit: ReadingUnit;
  /** 服务端 publication-owned 章标题；null 时回退显示 chapter_id。 */
  readonly chapterTitle?: string | null;
  /** true 时在正文前渲染章边界标题（仅章首 unit）。 */
  readonly showChapterHeading?: boolean;
  readonly expandedAnchorId?: string | null;
  readonly sourceClient?: ChapterSourceClient;
  readonly renderEvent?: ReadingEventRenderer;
  readonly renderSource?: ReadingSourceRenderer;
  /** 切换引用展开；anchorId 为 null 表示关闭。 */
  readonly onToggleSource?: (unitId: string, anchorId: string | null) => void;
}

function DefaultEventSpan({ segment }: { segment: ReadingEventSegment }) {
  const span = segment.span;
  const uncertain = span.status !== "resolved";
  return (
    <span
      className={uncertain ? "rcw-event rcw-event-uncertain" : "rcw-event"}
      data-test={uncertain ? "reading-event-span-uncertain" : "reading-event-span"}
      data-status={span.status}
      data-relation={span.relation}
      data-span={span.span_id}
    >
      {segment.text}
    </span>
  );
}

/**
 * 单个 unit 的正文内容。source anchors 只在服务端给出时提供按需入口；
 * 展开复用第一轮原文面板，关闭交给 ChapterSourceReference 恢复触发焦点。
 */
export default function ReadingContent({
  unit,
  chapterTitle,
  showChapterHeading = false,
  expandedAnchorId = null,
  sourceClient,
  renderEvent,
  renderSource,
  onToggleSource,
}: ReadingContentProps) {
  const segments = unit.segments ?? [];
  const anchors = (unit.source_anchor_ids ?? [])
    .map((anchor) => (anchor ?? "").trim())
    .filter((anchor) => anchor.length > 0);

  const renderSourceSlot: ReadingSourceRenderer =
    renderSource ??
    ((slot) => (
      <ChapterSourceReference
        publicationId={slot.unit.publication_id}
        anchorId={slot.anchorId}
        anchorLabel={slot.anchorLabel}
        client={sourceClient}
        onClose={slot.onClose}
      />
    ));

  return (
    <div className="rcw-content">
      {showChapterHeading ? (
        <header
          className="rcw-chapter-heading"
          data-test="reading-chapter-heading"
          data-chapter-id={unit.chapter_id}
        >
          <p className="rcw-chapter-eyebrow">章</p>
          <h2 className="rcw-chapter-title">{chapterTitle ?? unit.chapter_id}</h2>
        </header>
      ) : null}

      <p className="rcw-unit-text" data-test="reading-unit-text">
        {segments.map((segment, index) =>
          segment.kind === "event" ? (
            <Fragment key={`event-${index}-${segment.span.span_id}`}>
              {renderEvent ? renderEvent({ segment, unit }) : <DefaultEventSpan segment={segment} />}
            </Fragment>
          ) : (
            <span data-test="reading-segment" key={`text-${index}`}>
              {segment.text}
            </span>
          ),
        )}
      </p>

      {anchors.length > 0 ? (
        <footer className="rcw-unit-sources">
          <p className="rcw-source-label">原文依据 · 按需查看，保持原出版物版本</p>
          <div className="rcw-source-buttons">
            {anchors.map((anchorId, index) => {
              const expanded = expandedAnchorId === anchorId;
              const label = anchors.length > 1 ? `查看原文 ${index + 1}` : "查看原文";
              return (
                <button
                  type="button"
                  key={anchorId}
                  className="rcw-source-toggle"
                  data-test="reading-source-toggle"
                  data-anchor={anchorId}
                  aria-expanded={expanded}
                  onClick={() => onToggleSource?.(unit.unit_id, expanded ? null : anchorId)}
                >
                  {expanded ? "收起原文" : label}
                </button>
              );
            })}
          </div>
          {expandedAnchorId ? (
            <div data-test="reading-source-slot" data-anchor={expandedAnchorId}>
              {renderSourceSlot({
                unit,
                anchorId: expandedAnchorId,
                anchorLabel: `第 ${unit.ordinal + 1} 段原文`,
                onClose: () => onToggleSource?.(unit.unit_id, null),
              })}
            </div>
          ) : null}
        </footer>
      ) : null}
    </div>
  );
}
