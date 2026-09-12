// C2-R2-T12 阅读定位控制器独立 fixture 场景（仅测试使用，不接生产 App）。
//
// 在 T02 基座上真实挂载 useReadingPosition，注入版本固定的 synthetic
// published DTO 形状与受控 locate 响应，用于验证 active unit、深链接/刷新、
// 返回栈、旧响应忽略、用户滚动打断与 storage 降级。所有数据显式 synthetic。

import { useCallback, useLayoutEffect, useMemo, useRef, useState, type ReactElement } from "react";

import {
  parseReadingFields,
  type ReadingUrlStrategy,
} from "../../../../../src/lib/reading-location";
import type {
  ContextEntityView,
  NarrativeTime,
  ReadingLocator,
  ReadingNavigationAction,
} from "../../../../../src/lib/reading-types";
import {
  useReadingPosition,
  type ReadingLocateResult,
  type ReadingPositionOptions,
  type ReadingUnitSnapshot,
} from "../../../../../src/hooks/useReadingPosition";
import { READING_FIXTURE_SAMPLE_NOTE } from "../types";
import type { ReadingScene } from "../types";

const STREAM_ID = "01890a5d-ac96-774b-bcce-b302099a8057";
const CATALOG_SHA = "c".repeat(64);
const UNIT_COUNT = 30;
const HEADER_HEIGHT = 64;

function unitId(ordinal: number): string {
  return `ru_${ordinal.toString(16).padStart(24, "0")}`;
}

interface FixtureUnit {
  readonly unitId: string;
  readonly ordinal: number;
  readonly text: string;
  readonly keyPhrase: string;
  readonly focusId: string | null;
}

const UNITS: FixtureUnit[] = Array.from({ length: UNIT_COUNT }, (_, ordinal) => ({
  unitId: unitId(ordinal),
  ordinal,
  text: `合成阅读段 ${ordinal}：本段用于验证定位控制器行为，不是真实史料译文。`,
  keyPhrase: `事件词 ${ordinal}`,
  focusId: ordinal % 5 === 0 ? `focus-${ordinal}` : null,
}));

const UNIT_BY_ID = new Map(UNITS.map((unit) => [unit.unitId, unit]));

function narrativeTime(ordinal: number): NarrativeTime {
  if (ordinal === 7) {
    return {
      mode: "unknown",
      status: "unknown",
      event_refs: [],
      from_block_id: null,
      observations: [],
      year_key: "unknown",
      period_key: "unknown",
      year_label: null,
      period_label: "时间未明确",
      precision: "unknown",
      continues_previous: false,
    };
  }
  const year = 208 + Math.floor(ordinal / 4);
  return {
    mode: "events",
    status: "resolved",
    event_refs: [`evt-${ordinal}`],
    from_block_id: null,
    observations: [],
    year_key: `gregorian:${year}`,
    period_key: `gregorian:${year}:8`,
    year_label: `公元 ${year} 年`,
    period_label: `史料八月`,
    precision: "month",
    continues_previous: ordinal % 4 !== 0,
  };
}

function contextEntities(ordinal: number): ContextEntityView[] {
  if (ordinal === 7) return [];
  return [
    {
      entity_ref: `ent-${ordinal}`,
      name: `人物${ordinal % 3}`,
      canonical_id: null,
      kind: "person",
      importance: "primary",
      source_anchor_ids: [],
      event_roles: [],
    },
    {
      entity_ref: `place-${ordinal}`,
      name: `地点${ordinal % 2}`,
      canonical_id: null,
      kind: "place",
      importance: "other",
      source_anchor_ids: [],
      event_roles: [],
    },
  ];
}

function snapshot(ordinal: number): ReadingUnitSnapshot {
  return {
    unitId: unitId(ordinal),
    ordinal,
    narrativeTime: narrativeTime(ordinal),
    contextEntities: contextEntities(ordinal),
  };
}

const FIXTURE_UNIT_SNAPSHOTS = new Map(UNITS.map((unit) => [unit.unitId, snapshot(unit.ordinal)]));

const FIXTURE_URL_STRATEGY: ReadingUrlStrategy = {
  parse: (url) => {
    const parsed = new URL(url, "https://loom.local");
    return parseReadingFields({
      stream_id: parsed.searchParams.get("stream"),
      catalog_sha: parsed.searchParams.get("catalog"),
      unit_id: parsed.searchParams.get("at"),
    });
  },
  build: (locator) => {
    const url = new URL(window.location.href);
    url.searchParams.set("stream", locator.stream_id);
    url.searchParams.set("catalog", locator.catalog_sha);
    url.searchParams.set("at", locator.unit_id);
    return `${url.pathname}${url.search}`;
  },
};

interface FixtureProps {
  readonly params: URLSearchParams;
}

function PositionFixture({ params }: FixtureProps): ReactElement {
  const storageMode = params.get("storage") === "off" ? null : undefined;
  const slowNextRef = useRef(false);
  const slowWindowNextRef = useRef(false);
  const [returnResult, setReturnResult] = useState<string>("");
  const [returnTokens, setReturnTokens] = useState<string[]>([]);
  const [previewCount, setPreviewCount] = useState(0);
  const [prependedHeight, setPrependedHeight] = useState(0);

  const getUnit = useCallback(
    (id: string): ReadingUnitSnapshot | null => FIXTURE_UNIT_SNAPSHOTS.get(id) ?? null,
    [],
  );

  const locate = useCallback(
    async (locator: ReadingLocator): Promise<ReadingLocateResult | null> => {
      const target = UNIT_BY_ID.get(locator.unit_id);
      if (!target) return null;
      if (target.ordinal === 29) throw new Error("controlled locate failure");
      const slow = slowNextRef.current;
      slowNextRef.current = false;
      if (slow) {
        await new Promise((resolve) => window.setTimeout(resolve, 800));
      }
      return { locator, unitIds: [target.unitId] };
    },
    [],
  );

  const resolveStart = useCallback(
    async (route: { stream_id: string; catalog_sha: string }): Promise<ReadingLocator | null> => {
      await new Promise((resolve) => window.setTimeout(resolve, 800));
      return {
        stream_id: route.stream_id,
        catalog_sha: route.catalog_sha,
        unit_id: unitId(0),
      };
    },
    [],
  );

  // 受控慢窗口加载：locate 已成功，但就绪等待期间允许用户滚动取消。
  const loadWindow = useCallback(async (locator: ReadingLocator): Promise<void> => {
    void locator;
    const slow = slowWindowNextRef.current;
    slowWindowNextRef.current = false;
    if (slow) {
      await new Promise((resolve) => window.setTimeout(resolve, 800));
    }
  }, []);

  const options: ReadingPositionOptions = useMemo(
    () => ({
      getUnit,
      locate,
      resolveStart,
      loadWindow,
      storage: storageMode,
      urlStrategy: FIXTURE_URL_STRATEGY,
      headerHeight: HEADER_HEIGHT,
      settleDelayMs: 120,
      preserveLayoutPosition: true,
    }),
    [getUnit, locate, resolveStart, loadWindow, storageMode],
  );

  const controller = useReadingPosition(options);
  useLayoutEffect(() => {
    controller.notifyLayoutChange();
  }, [prependedHeight, controller.notifyLayoutChange]);

  const navigateAxis = () => {
    const target = UNITS[10]!;
    const action: ReadingNavigationAction = {
      kind: "axis",
      locator: { stream_id: STREAM_ID, catalog_sha: CATALOG_SHA, unit_id: target.unitId },
    };
    controller.navigate(action);
  };

  const navigateEvent = () => {
    const target = UNITS[15]!;
    const action: ReadingNavigationAction = {
      kind: "event",
      locator: { stream_id: STREAM_ID, catalog_sha: CATALOG_SHA, unit_id: target.unitId },
      event_id: `evt-${target.ordinal}`,
    };
    controller.navigate(action);
  };

  const delayedNavigate = () => {
    slowNextRef.current = true;
    const target = UNITS[28]!;
    controller.navigate({
      kind: "locate",
      locator: { stream_id: STREAM_ID, catalog_sha: CATALOG_SHA, unit_id: target.unitId },
    });
  };

  const naturalScrollTo = (ordinal: number) => {
    const target = UNITS[ordinal];
    if (!target) return;
    const node = document.querySelector(
      `[data-reading-unit][data-unit-id="${target.unitId}"]`,
    ) as HTMLElement | null;
    if (!node) return;
    window.scrollTo({ top: node.getBoundingClientRect().top + window.scrollY - 40 });
  };

  // 移除 URL 的 at 后走 resolveStart（受控迟到 800ms），用于验证起点解析被 fence。
  const delayedStartRestore = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete("at");
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}`);
    controller.restoreFromUrl();
  };

  const failLocate = () => {
    const target = UNITS[29]!;
    controller.navigate({
      kind: "locate",
      locator: { stream_id: STREAM_ID, catalog_sha: CATALOG_SHA, unit_id: target.unitId },
    });
  };

  const slowWindowNavigate = () => {
    slowWindowNextRef.current = true;
    const target = UNITS[25]!;
    controller.navigate({
      kind: "locate",
      locator: { stream_id: STREAM_ID, catalog_sha: CATALOG_SHA, unit_id: target.unitId },
    });
  };

  const rememberReturn = () => {
    const remembered = controller.rememberReturnTarget();
    if (!remembered) {
      setReturnResult("没有可保存的定位");
      return;
    }
    setReturnTokens((tokens) => [...tokens, remembered.token]);
    setReturnResult(remembered.persisted ? "返回目标已保存" : "存储不可用，返回目标未保存");
  };

  const restoreReturn = (token: string) => {
    const resolved = controller.restoreReturnToken(token);
    setReturnResult(resolved ? `已按返回 token 恢复 ${resolved.unit_id}` : "token 失效：进入相关正文");
  };

  const restoreInvalidReturn = () => {
    const resolved = controller.restoreReturnToken(`rt_${"f".repeat(32)}`);
    setReturnResult(resolved ? "不应发生：无效 token 被接受" : "token 失效：进入相关正文（无外部跳转）");
  };

  return (
    <main data-test="position-scene" data-synthetic="true" data-storage={storageMode === null ? "off" : "on"}
      style={{ overflowAnchor: "none" }}>
      <header
        data-test="position-header"
        style={{ position: "sticky", top: 0, height: HEADER_HEIGHT, background: "#fff", zIndex: 2 }}
      >
        <span data-test="position-active-unit" data-unit-id={controller.activeUnitId ?? ""} data-ordinal={controller.activeOrdinal ?? -1}>
          active={controller.activeUnitId ?? "none"}
        </span>
        <span data-test="position-nav-state">{controller.navigationState}</span>
        <span data-test="position-time-label">{controller.narrativeTime?.period_label ?? "—"}</span>
        <span data-test="position-context-count">{controller.contextEntities.length}</span>
        <span data-test="position-issue">{controller.issue ? controller.issue.code : ""}</span>
        <span data-test="position-url">{typeof window === "undefined" ? "" : `${window.location.pathname}${window.location.search}`}</span>
        <span data-test="position-preview-count">{previewCount}</span>
      </header>

      <section
        data-test="position-controls"
        style={{ position: "fixed", left: 0, right: 0, bottom: 0, background: "#fff", zIndex: 3, padding: "6px 0" }}
      >
        <button type="button" data-test="position-nav-axis" onClick={navigateAxis}>
          轴定位到 u10
        </button>
        <button type="button" data-test="position-prepend" onClick={() => {
          setPrependedHeight((height) => height + 46);
          window.setTimeout(() => setPrependedHeight((height) => height + 5954), 150);
        }}>
          延迟补载前文
        </button>
        <button type="button" data-test="position-nav-event" onClick={navigateEvent}>
          进入事件 u15
        </button>
        <button type="button" data-test="position-delayed-nav" onClick={delayedNavigate}>
          迟到定位 u28
        </button>
        <button type="button" data-test="position-delayed-start" onClick={delayedStartRestore}>
          迟到起点解析
        </button>
        <button type="button" data-test="position-fail-locate" onClick={failLocate}>
          失败定位 u29
        </button>
        <button type="button" data-test="position-slow-window-nav" onClick={slowWindowNavigate}>
          慢窗口定位 u25
        </button>
        <button type="button" data-test="position-scroll-u02" onClick={() => naturalScrollTo(2)}>
          自然滚动 u02
        </button>
        <button
          type="button"
          data-test="position-preview"
          onClick={() => {
            controller.previewEvent("evt-3");
            setPreviewCount((count) => count + 1);
          }}
        >
          预览事件
        </button>
        <button type="button" data-test="position-remember-return" onClick={rememberReturn}>
          记住返回目标
        </button>
        <button type="button" data-test="position-restore-return" onClick={() => restoreReturn(returnTokens.at(-1) ?? "")}>
          返回阅读
        </button>
        <button type="button" data-test="position-invalid-token" onClick={restoreInvalidReturn}>
          失效 token
        </button>
        <div data-test="position-return-tokens">
          {returnTokens.map((token, index) => (
            <button
              type="button"
              key={token}
              data-test={`position-return-token-${index}`}
              data-token={token}
              onClick={() => restoreReturn(token)}
            >
              返回 token {index}
            </button>
          ))}
        </div>
      </section>

      <p data-test="position-return-result">{returnResult}</p>
      <p data-test="position-sample-note">{READING_FIXTURE_SAMPLE_NOTE}</p>
      <p data-test="position-sample-note">{READING_FIXTURE_SAMPLE_NOTE}</p>

      <div data-test="position-prepended" data-height={prependedHeight} style={{ height: prependedHeight }} />
      <div data-test="position-units">
        {UNITS.map((unit) => (
          <section
            key={unit.unitId}
            data-test="position-unit"
            data-reading-unit="true"
            data-unit-id={unit.unitId}
            data-ordinal={unit.ordinal}
            data-text={unit.text}
            style={{ minHeight: 320, padding: "12px 0" }}
          >
            <h2>{narrativeTime(unit.ordinal).year_label ?? "时间未明确"}</h2>
            <p>
              {unit.text}
              {unit.focusId ? (
                <span data-test="position-event-trigger" data-focus-id={unit.focusId} tabIndex={0}>
                  （{unit.keyPhrase}）
                </span>
              ) : null}
            </p>
            <span data-test="position-unit-time">{narrativeTime(unit.ordinal).period_label}</span>
            <span data-test="position-unit-context">{contextEntities(unit.ordinal).length}</span>
          </section>
        ))}
      </div>
    </main>
  );
}

const scenes: ReadingScene[] = [
  {
    name: "main",
    suite: "position",
    label: "定位控制器：深链接/返回栈/旧响应/预览",
    synthetic: true,
    render: (params) => <PositionFixture params={params} />,
  },
  {
    name: "storage-off",
    suite: "position",
    label: "定位控制器：存储不可用降级",
    synthetic: true,
    render: (params) => <PositionFixture params={params} />,
  },
];

export default scenes;
