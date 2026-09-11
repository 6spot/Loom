// C2-R2-T02 harness 基座场景的 fixture 组件（仅测试使用，不进生产构建）。
//
// 它不是 T10–T14 的生产组件：只把 published DTO 形状渲染成可断言的 DOM，
// 並提供受控響應注入點，證明基座能發現場景、掛載、操作與顯式報錯。
// 事件分段用 React 文本節點渲染，瀏覽器絕不替換/猜測事件詞。

import { useMemo, useState } from "react";
import type { ContextEntity, ReadingTimeGroup, ReadingUnit, UnitSegment } from "../types";
import { FIXTURE_GROUPS, FIXTURE_PAGE1 } from "./fixtures";
import { loadNextPage, LATE_DELAY_MS, type LoadMode } from "./controlled";

type LoadState =
  | { kind: "idle" }
  | { kind: "loading"; mode: LoadMode }
  | { kind: "error"; message: string }
  | { kind: "empty" };

function SegmentView({ segment, index }: { segment: UnitSegment; index: number }) {
  if (segment.kind === "event") {
    const uncertain = segment.status !== "resolved";
    return (
      <span
        data-test={uncertain ? "reading-event-span-uncertain" : "reading-event-span"}
        data-status={segment.status}
        data-relation={segment.relation}
        data-span={segment.span_id}
        key={index}
      >
        {segment.text}
      </span>
    );
  }
  return (
    <span data-test="reading-segment" key={index}>
      {segment.text}
    </span>
  );
}

function ContextView({ entities }: { entities: ContextEntity[] }) {
  if (entities.length === 0) {
    return <span data-test="reading-context-empty">本段无明确关联</span>;
  }
  return (
    <ul data-test="reading-context">
      {entities.map((entity) => (
        <li
          key={entity.entity_ref}
          data-test="reading-context-entity"
          data-entity-type={entity.entity_type}
          data-importance={entity.importance}
        >
          {entity.display_name}
        </li>
      ))}
    </ul>
  );
}

function GroupView({ group }: { group: ReadingTimeGroup }) {
  return (
    <div data-test="reading-group" data-group-id={group.group_id} data-precision={group.precision}>
      <span data-test="reading-group-year">{group.year_label}</span>
      <span data-test="reading-group-period">{group.period_label}</span>
      {group.continues_previous ? <span data-test="reading-group-continues">（延续）</span> : null}
    </div>
  );
}

export function BaseReadingWindow() {
  const [units, setUnits] = useState<ReadingUnit[]>(FIXTURE_PAGE1);
  const [activeOrdinal, setActiveOrdinal] = useState(0);
  const [loadState, setLoadState] = useState<LoadState>({ kind: "idle" });
  const [loadedPages, setLoadedPages] = useState(0);

  const activeUnit = useMemo(
    () => units.find((unit) => unit.ordinal === activeOrdinal) ?? units[0],
    [units, activeOrdinal],
  );

  async function requestNext(mode: LoadMode) {
    setLoadState({ kind: "loading", mode });
    try {
      const page = await loadNextPage(mode);
      if (page.length === 0) {
        setLoadState({ kind: "empty" });
        return;
      }
      setUnits((current) => {
        const seen = new Set(current.map((unit) => unit.unit_id));
        return [...current, ...page.filter((unit) => !seen.has(unit.unit_id))];
      });
      setLoadedPages((count) => count + 1);
      setLoadState({ kind: "idle" });
    } catch (error) {
      setLoadState({ kind: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  return (
    <main data-test="reading-harness" data-synthetic="true">
      <p data-test="reading-synthetic-note">
        合成 fixture：仅演示 published DTO 形状与受控响应，非真实后端 / 非真实模型输出。
      </p>

      <section data-test="reading-timeline" aria-label="阅读时间轴">
        {FIXTURE_GROUPS.map((group) => (
          <GroupView group={group} key={group.group_id} />
        ))}
      </section>

      <section data-test="reading-window" aria-label="连续正文窗口">
        {units.map((unit) => (
          <article
            data-test="reading-unit"
            data-ordinal={unit.ordinal}
            data-active={unit.ordinal === activeOrdinal}
            data-synthetic={unit.synthetic}
            key={unit.unit_id}
          >
            <button
              type="button"
              data-test="reading-unit-activate"
              onClick={() => setActiveOrdinal(unit.ordinal)}
            >
              第 {unit.ordinal + 1} 段
            </button>
            <p data-test="reading-unit-text">
              {unit.segments.map((segment, index) => (
                <SegmentView index={index} key={`${unit.unit_id}-${index}`} segment={segment} />
              ))}
            </p>
            <ContextView entities={unit.context_entities} />
          </article>
        ))}
      </section>

      <section data-test="reading-load-controls">
        <button type="button" data-test="reading-load-next-ok" onClick={() => void requestNext("ok")}>
          读下一页
        </button>
        <button type="button" data-test="reading-load-next-fail" onClick={() => void requestNext("fail")}>
          下一页·受控失败
        </button>
        <button type="button" data-test="reading-load-next-late" onClick={() => void requestNext("late")}>
          下一页·受控迟到
        </button>
        <button type="button" data-test="reading-load-next-blank" onClick={() => void requestNext("blank")}>
          下一页·空白
        </button>
        <span data-test="reading-loaded-pages">{loadedPages}</span>
      </section>

      {loadState.kind === "loading" ? (
        <p data-test="reading-loading" data-mode={loadState.mode}>
          载入中…
        </p>
      ) : null}
      {loadState.kind === "error" ? (
        <p data-test="reading-load-error" role="alert">
          载入失败：{loadState.message}
        </p>
      ) : null}
      {loadState.kind === "empty" ? (
        <p data-test="reading-load-empty">没有更多正文（显式空白，不伪造内容）</p>
      ) : null}

      <p data-test="reading-active-unit" data-ordinal={activeUnit ? activeUnit.ordinal : -1}>
        当前第 {(activeUnit ? activeUnit.ordinal : 0) + 1} 段
      </p>
      <p data-test="reading-late-delay">{LATE_DELAY_MS}</p>
    </main>
  );
}
