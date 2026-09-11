// C2-R2-T13 事件目标选择器：在当前事件有多个正文位置时，让用户按来源/章/位置
// 明确选择，而不是默认取第一个字符串命中。合同见 reading-experience.md §5 与
// continuous-reading.md §7：
//   - relation=current 才是「发生位置」；mention 只作为「提及」单独标注；
//   - 没有 current 目标时如实提示，不自动跳到回溯提及；
//   - 只消费服务端分页好的 EventTarget，不按名称重新查找。
//
// 尚未挂接 App：T15 负责通过 render slot/callback 组合到阅读页面。

import type { EventTarget } from "../../lib/reading-types";

export type ReadingTargetPickerMode = "locate" | "other";

export interface ReadingTargetPickerProps {
  readonly mode: ReadingTargetPickerMode;
  readonly targets: readonly EventTarget[];
  readonly currentCount: number;
  readonly mentionCount: number;
  readonly selectedUnitId?: string | null;
  readonly onChoose: (target: EventTarget) => void;
  readonly hasMore?: boolean;
  readonly loadingMore?: boolean;
  readonly onLoadMore?: () => void;
}

function sourceLabel(target: EventTarget): string {
  const source = target.source_title?.trim();
  if (source) return source;
  return target.stream_id;
}

function chapterLabel(target: EventTarget): string {
  const chapter = target.chapter_title?.trim();
  if (chapter) return chapter;
  return target.chapter_id;
}

function relationLabel(relation: EventTarget["relation"]): string {
  return relation === "current" ? "发生位置" : "提及";
}

function TargetOption({
  target,
  selected,
  onChoose,
}: {
  readonly target: EventTarget;
  readonly selected: boolean;
  readonly onChoose: (target: EventTarget) => void;
}) {
  return (
    <li className="rev-target-item">
      <button
        type="button"
        className="rev-target-option"
        data-test="reading-target-option"
        data-relation={target.relation}
        data-stream={target.stream_id}
        data-unit={target.unit_id}
        data-publication={target.publication_id}
        data-selected={selected}
        aria-pressed={selected}
        onClick={() => onChoose(target)}
      >
        <span className="rev-target-source" data-test="reading-target-source">
          {sourceLabel(target)}
        </span>
        <span className="rev-target-chapter" data-test="reading-target-chapter">
          {chapterLabel(target)}
        </span>
        <span className="rev-target-excerpt" data-test="reading-target-excerpt">
          {target.excerpt}
        </span>
        <span className="rev-target-relation" data-test="reading-target-relation">
          {relationLabel(target.relation)}
        </span>
      </button>
    </li>
  );
}

function TargetGroup({
  kind,
  title,
  targets,
  selectedUnitId,
  onChoose,
}: {
  readonly kind: "current" | "mention";
  readonly title: string;
  readonly targets: readonly EventTarget[];
  readonly selectedUnitId: string | null;
  readonly onChoose: (target: EventTarget) => void;
}) {
  return (
    <div className="rev-target-group" data-test={`reading-target-${kind}-group`}>
      <p className="rev-target-group-title">{title}</p>
      {targets.length === 0 ? (
        <p className="rev-target-group-empty" data-test={`reading-target-${kind}-empty`}>
          位置分页中…
        </p>
      ) : (
        <ul className="rev-target-list">
          {targets.map((target) => (
            <TargetOption
              key={`${target.span_id}-${target.unit_id}`}
              target={target}
              selected={target.unit_id === selectedUnitId}
              onChoose={onChoose}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

export default function ReadingTargetPicker({
  mode,
  targets,
  currentCount,
  mentionCount,
  selectedUnitId = null,
  onChoose,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
}: ReadingTargetPickerProps) {
  const currentTargets = targets.filter((target) => target.relation === "current");
  const mentionTargets = targets.filter((target) => target.relation === "mention");
  const heading = mode === "locate" ? "选择发生位置" : "其他记载";

  return (
    <div className="rev-picker" data-test="reading-target-picker" data-mode={mode}>
      <p className="rev-picker-title" data-test="reading-target-picker-title">
        {heading}
      </p>

      {mode === "locate" ? (
        currentCount === 0 ? (
          <p className="rev-picker-empty" data-test="reading-target-empty" role="status">
            暂无已收录发生段落
            {mentionCount > 0 ? "，可在「其他记载」查看仅作提及的来源。" : "。"}
          </p>
        ) : (
          <TargetGroup
            kind="current"
            title="发生位置"
            targets={currentTargets}
            selectedUnitId={selectedUnitId}
            onChoose={onChoose}
          />
        )
      ) : (
        <>
          {currentCount > 0 ? (
            <TargetGroup
              kind="current"
              title="发生位置"
              targets={currentTargets}
              selectedUnitId={selectedUnitId}
              onChoose={onChoose}
            />
          ) : null}
          {mentionCount > 0 ? (
            <TargetGroup
              kind="mention"
              title="提及（非发生位置）"
              targets={mentionTargets}
              selectedUnitId={selectedUnitId}
              onChoose={onChoose}
            />
          ) : null}
        </>
      )}

      {hasMore && onLoadMore ? (
        <button
          type="button"
          className="rev-picker-load-more"
          data-test="reading-target-load-more"
          onClick={onLoadMore}
          disabled={loadingMore}
        >
          {loadingMore ? "载入中…" : "加载更多位置"}
        </button>
      ) : null}
    </div>
  );
}
