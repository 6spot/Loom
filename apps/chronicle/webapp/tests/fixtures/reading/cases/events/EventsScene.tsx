// C2-R2-T13 events suite fixture 场景外壳（仅测试使用，不进生产构建）。
//
// 只负责把生产组件 ReadingEventTrigger 挂到合成 published-DTO 数据源上，记录
// 发出的导航动作与按需加载次数，供浏览器 spec 断言；它不冒充真实后端，也不
// 预取任何事件：只有组件触发 hover/focus/tap 时才调用 loader。

import { useRef, useState } from "react";
import ReadingEventTrigger from "../../../../../src/components/reading/ReadingEventTrigger";
import type {
  EventPreview,
  EventTargetPage,
  ReadingLocator,
  ReadingNavigationAction,
  ReadingSegment,
} from "../../../../../src/lib/reading-types";
import { EVENTS_CATALOG, CURRENT_READING_LOCATOR } from "./fixtures";

export interface SceneEventResponse {
  readonly preview: EventPreview;
  readonly targets: EventTargetPage;
  readonly previewDelayMs?: number;
  readonly targetDelayMs?: number;
  /** 前 N 次 preview 请求受控失败，之后成功（用于重试场景）。 */
  readonly previewFailures?: number;
  /** 前 N 次 targets 请求受控失败，之后成功（用于位置重试场景）。 */
  readonly targetFailures?: number;
}

export interface EventsSceneProps {
  readonly heading: string;
  readonly unitText: string;
  readonly segments: readonly ReadingSegment[];
  readonly responses: Readonly<Record<string, SceneEventResponse>>;
  readonly reducedMotion?: boolean;
  readonly readingLocator?: ReadingLocator | null;
}

interface CallCount {
  preview: number;
  target: number;
}

export function EventsScene({
  heading,
  unitText,
  segments,
  responses,
  reducedMotion,
  readingLocator = CURRENT_READING_LOCATOR,
}: EventsSceneProps) {
  const [lastAction, setLastAction] = useState<ReadingNavigationAction | null>(null);
  const [counts, setCounts] = useState<Record<string, CallCount>>({});
  const failures = useRef<Record<string, CallCount>>({});

  function record(eventId: string, kind: keyof CallCount) {
    setCounts((current) => {
      const row = current[eventId] ?? { preview: 0, target: 0 };
      return { ...current, [eventId]: { ...row, [kind]: row[kind] + 1 } };
    });
  }

  function takeFailure(eventId: string, kind: keyof CallCount, limit: number): boolean {
    const row = failures.current[eventId] ?? { preview: 0, target: 0 };
    if (row[kind] >= limit) return false;
    failures.current[eventId] = { ...row, [kind]: row[kind] + 1 };
    return true;
  }

  function loadPreview(eventId: string): Promise<EventPreview> {
    record(eventId, "preview");
    const response = responses[eventId];
    const delay = response?.previewDelayMs ?? 0;
    const limit = response?.previewFailures ?? 0;
    return new Promise((resolve, reject) => {
      window.setTimeout(() => {
        if (takeFailure(eventId, "preview", limit)) {
          reject(new Error(`controlled preview failure for ${eventId}`));
          return;
        }
        if (!response) {
          reject(new Error(`no fixture preview for ${eventId}`));
          return;
        }
        resolve(response.preview);
      }, delay);
    });
  }

  function loadTargets(eventId: string): Promise<EventTargetPage> {
    record(eventId, "target");
    const response = responses[eventId];
    const delay = response?.targetDelayMs ?? 0;
    const limit = response?.targetFailures ?? 0;
    return new Promise((resolve, reject) => {
      window.setTimeout(() => {
        if (takeFailure(eventId, "target", limit)) {
          reject(new Error(`controlled target failure for ${eventId}`));
          return;
        }
        if (!response) {
          reject(new Error(`no fixture targets for ${eventId}`));
          return;
        }
        resolve(response.targets);
      }, delay);
    });
  }

  const totalPreview = Object.values(counts).reduce((sum, row) => sum + row.preview, 0);
  const totalTarget = Object.values(counts).reduce((sum, row) => sum + row.target, 0);

  return (
    <main data-test="events-fixture" data-synthetic="true">
      <p data-test="reading-synthetic-note">
        合成 fixture：只演示 published DTO 形状与事件预览交互，非真实后端、非真实模型输出，也不冒充史料。
      </p>
      <h1 data-test="events-fixture-heading">{heading}</h1>

      <article className="events-fixture-body" data-test="events-body" data-text={unitText}>
        <p className="events-fixture-sentence" data-test="events-sentence" data-text={unitText}>
          {segments.map((segment, index) =>
            segment.kind === "text" ? (
              <span data-test="events-text-segment" key={`text-${index}`}>
                {segment.text}
              </span>
            ) : (
              <ReadingEventTrigger
                key={`${segment.span.span_id}-${index}`}
                segment={segment}
                catalogSha={EVENTS_CATALOG}
                locator={readingLocator}
                loadPreview={loadPreview}
                loadTargets={loadTargets}
                onNavigate={setLastAction}
                reducedMotion={reducedMotion}
              />
            ),
          )}
        </p>
      </article>

      <output
        data-test="events-last-action"
        data-kind={lastAction?.kind ?? ""}
        data-event-id={lastAction && "event_id" in lastAction ? lastAction.event_id : ""}
        data-unit={lastAction?.locator.unit_id ?? ""}
        data-stream={lastAction?.locator.stream_id ?? ""}
        data-catalog={lastAction?.locator.catalog_sha ?? ""}
      />
      <output
        data-test="events-call-counts"
        data-preview={totalPreview}
        data-target={totalTarget}
        data-detail={JSON.stringify(counts)}
      />
    </main>
  );
}
