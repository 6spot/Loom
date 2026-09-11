// C2-R2-T13 事件预览内容（轻量卡 / 窄屏面板的内层）。合同见
// reading-experience.md §5：事件名、来源时间与分歧、简短已有译文摘录或来源说明，
// 以及「查看事件 / 定位发生位置 / 其他记载」；来源归属保留，时间分歧显式呈现，
// 载入失败保留正文并允许重试。
//
// 本组件只消费 typed EventPreview / EventTargetPage，不自行猜测关系、不按名称跳转；
// 交互外壳（portal 卡片、窄屏面板、悬停/焦点/触屏、迟到响应）在 ReadingEventTrigger。
// T15 负责挂接 T09 client / T12 controller。

import type {
  EventPreview,
  EventPreviewSource,
  EventTarget,
  EventTargetPage,
} from "../../lib/reading-types";
import ReadingTargetPicker, { type ReadingTargetPickerMode } from "./ReadingTargetPicker";

export interface ReadingEventPreviewProps {
  readonly fallbackName: string;
  readonly preview: EventPreview | null;
  readonly targets: EventTargetPage | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly targetsError: string | null;
  readonly targetsLoading: boolean;
  readonly picker: ReadingTargetPickerMode | null;
  readonly selectedUnitId?: string | null;
  readonly canViewEvent: boolean;
  readonly onRetry: () => void;
  readonly onRetryTargets: () => void;
  readonly onViewEvent: () => void;
  readonly onLocate: () => void;
  readonly onOtherRecords: () => void;
  readonly onChooseTarget: (target: EventTarget) => void;
  readonly onLoadMoreTargets: () => void;
  readonly loadingMoreTargets?: boolean;
}

/** 只复用服务端给出的原始时间观察；不推算、不取 canonical 聚合年份。 */
export function sourceTimeText(source: EventPreviewSource): string {
  const texts = source.observations
    .map((observation) => observation.original_text?.trim())
    .filter((text): text is string => Boolean(text));
  if (texts.length === 0) return "时间未明确";
  return texts.join(" / ");
}

/** 多来源原始时间不一致时返回分歧说明；一致或缺失时返回 null。 */
export function describeTimeDivergence(sources: readonly EventPreviewSource[]): string | null {
  const nonEmpty = sources
    .map((source) => ({ title: source.source_title, text: sourceTimeText(source) }))
    .filter((row) => row.text !== "时间未明确");
  const distinct = new Set(nonEmpty.map((row) => row.text));
  if (distinct.size <= 1) return null;
  const detail = nonEmpty.map((row) => `${row.title}：${row.text}`).join("；");
  return `来源时间不一致（${detail}）`;
}

function SourceRow({ source }: { readonly source: EventPreviewSource }) {
  return (
    <li className="rev-source" data-test="reading-event-preview-source" data-source={source.source_title}>
      <p className="rev-source-title" data-test="reading-event-source-title">
        {source.source_title}
      </p>
      <p className="rev-source-time" data-test="reading-event-source-time">
        {sourceTimeText(source)}
      </p>
      {source.excerpt ? (
        <p className="rev-source-excerpt" data-test="reading-event-preview-excerpt">
          {source.excerpt}
          {source.excerpt_more ? "…" : ""}
        </p>
      ) : (
        <p className="rev-source-note" data-test="reading-event-preview-no-excerpt">
          暂无已发布译文摘录
        </p>
      )}
      {source.original_entry ? (
        <p className="rev-source-note" data-test="reading-event-preview-original-entry">
          可查看该来源原文
        </p>
      ) : null}
    </li>
  );
}

export default function ReadingEventPreview({
  fallbackName,
  preview,
  targets,
  loading,
  error,
  targetsError,
  targetsLoading,
  picker,
  selectedUnitId = null,
  canViewEvent,
  onRetry,
  onRetryTargets,
  onViewEvent,
  onLocate,
  onOtherRecords,
  onChooseTarget,
  onLoadMoreTargets,
  loadingMoreTargets = false,
}: ReadingEventPreviewProps) {
  const name = preview?.name?.trim() || fallbackName;
  const divergence = preview ? describeTimeDivergence(preview.sources) : null;
  const currentCount = targets?.current_count ?? 0;
  const mentionCount = targets?.mention_count ?? 0;

  return (
    <div className="rev-body">
      <p className="rev-name" data-test="reading-event-preview-name">
        {name}
      </p>

      {loading ? (
        <p className="rev-loading" data-test="reading-event-preview-loading" role="status">
          载入中…
        </p>
      ) : null}

      {error ? (
        <div className="rev-error" data-test="reading-event-preview-error" role="alert">
          <p className="rev-error-text">{error}</p>
          <button
            type="button"
            className="rev-button rev-button-retry"
            data-test="reading-event-preview-retry"
            onClick={onRetry}
          >
            重试
          </button>
        </div>
      ) : null}

      {preview && !error ? (
        <>
          <ul className="rev-sources" data-test="reading-event-sources">
            {preview.sources.map((source, index) => (
              <SourceRow key={`${source.source_title}-${index}`} source={source} />
            ))}
          </ul>
          <p className="rev-source-count" data-test="reading-event-preview-source-count">
            共 {preview.source_count} 个来源
            {preview.has_more_sources ? "，仅列已取回的部分" : ""}
          </p>
          {divergence ? (
            <p className="rev-divergence" data-test="reading-event-preview-time-divergence" role="note">
              {divergence}
            </p>
          ) : null}

          <div className="rev-actions" data-test="reading-event-preview-actions">
            <button
              type="button"
              className="rev-button"
              data-test="reading-event-preview-view"
              onClick={onViewEvent}
              disabled={!canViewEvent}
            >
              查看事件
            </button>
            <button
              type="button"
              className="rev-button"
              data-test="reading-event-preview-locate"
              data-has-current={currentCount > 0}
              onClick={onLocate}
            >
              定位发生位置
            </button>
            <button
              type="button"
              className="rev-button"
              data-test="reading-event-preview-other"
              onClick={onOtherRecords}
            >
              其他记载
            </button>
          </div>

          {targetsError ? (
            <div
              className="rev-error rev-targets-error"
              data-test="reading-event-targets-error"
              role="alert"
              aria-label="事件位置载入失败"
            >
              <p className="rev-error-text">{targetsError}</p>
              <button
                type="button"
                className="rev-button rev-button-retry"
                data-test="reading-event-targets-retry"
                onClick={onRetryTargets}
              >
                重试位置
              </button>
            </div>
          ) : null}
          {targetsLoading && !targetsError ? (
            <p className="rev-loading" data-test="reading-event-targets-loading" role="status">
              位置载入中…
            </p>
          ) : null}
        </>
      ) : null}

      {picker && targets ? (
        <ReadingTargetPicker
          mode={picker}
          targets={targets.targets}
          currentCount={currentCount}
          mentionCount={mentionCount}
          selectedUnitId={selectedUnitId}
          onChoose={onChooseTarget}
          hasMore={targets.has_more}
          loadingMore={loadingMoreTargets}
          onLoadMore={onLoadMoreTargets}
        />
      ) : null}
    </div>
  );
}
