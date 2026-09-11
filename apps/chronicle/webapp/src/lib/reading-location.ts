// Chronicle 第二轮阅读定位纯 helper（C2-R2-T12）。
//
// 归属：typed locator 解析/构造与合法性、参考线 active-unit 选择、rAF 合批、
// 显式导航/restoring/user-interrupted 状态机。运行时行为（滚动、history、
// 恢复）在 `hooks/useReadingPosition.ts`；本模块不接 App/router，不直接依赖
// T10 内容窗口实现。状态机唯一依据 reading-experience.md §4/§6。
//
// 安全边界：任何 URL 只由校验过的 {stream_id, catalog_sha, unit_id} 字段构建；
// 解析只接受本站 `/read/...` 目标，外部 return_to、模型生成 URL 一律拒绝。

import type { ReadingLocator } from "./reading-types";
import { isReadingLocator } from "./reading-types";

/** 唯一阅读页路由前缀（reading-experience.md §1）。 */
export const READING_ROUTE_PREFIX = "/read";
/** 构造同站/解析相对 URL 时使用的固定 origin，不发起网络请求。 */
export const READING_BASE_ORIGIN = "https://loom.local";
/** 详情页携带 return token 的 query 参数名。 */
export const READING_RETURN_PARAM = "return";

const UUID_V7 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const UNIT_ID = /^ru_[0-9a-f]{24}$/;

// ---------------------------------------------------------------------------
// Typed locator 解析与构造
// ---------------------------------------------------------------------------

export type ReadingUrlIssueCode =
  | "unsupported_target"
  | "missing_stream"
  | "missing_catalog"
  | "missing_unit"
  | "duplicate_param"
  | "unknown_param"
  | "invalid_stream"
  | "invalid_catalog"
  | "invalid_unit"
  | "snapshot_mismatch";

export interface ReadingUrlIssue {
  readonly code: ReadingUrlIssueCode;
  readonly detail: string;
}

/** 解析出的定位意图；`unit_id` 缺省表示从首段开始（reading-experience.md §1）。 */
export interface ReadingLocation {
  readonly stream_id: string;
  readonly catalog_sha: string;
  readonly unit_id: string | null;
}

export type ReadingUrlParse =
  | { readonly ok: true; readonly location: ReadingLocation }
  | { readonly ok: false; readonly issue: ReadingUrlIssue };

function fail(code: ReadingUrlIssueCode, detail: string): ReadingUrlParse {
  return { ok: false, issue: { code, detail } };
}

export function readingIssue(
  code: ReadingUrlIssueCode,
  detail: string,
): ReadingUrlIssue {
  return { code, detail };
}

const ALLOWED_PARAMS = new Set(["catalog", "at"]);

export interface ReadingFieldsInput {
  readonly stream_id?: string | null;
  readonly catalog_sha?: string | null;
  readonly unit_id?: string | null;
}

/**
 * 校验拆分后的三字段。生产 URL 解析与测试/适配层的 query 映射共用同一套合法性
 * 规则，避免出现第二套 locator 校验。
 */
export function parseReadingFields(input: ReadingFieldsInput): ReadingUrlParse {
  const stream = input.stream_id;
  if (stream === null || stream === undefined || stream.length === 0) {
    return fail("missing_stream", "stream_id is required");
  }
  if (!UUID_V7.test(stream)) {
    return fail("invalid_stream", "stream_id is not a UUIDv7");
  }

  const catalog = input.catalog_sha;
  if (catalog === null || catalog === undefined || catalog.length === 0) {
    return fail("missing_catalog", "catalog is required");
  }
  if (!SHA256.test(catalog)) {
    return fail("invalid_catalog", "catalog is not a sha256 hex digest");
  }

  const unit = input.unit_id ?? null;
  if (unit !== null && unit.length === 0) {
    return fail("invalid_unit", "at must not be empty");
  }
  if (unit !== null && !UNIT_ID.test(unit)) {
    return fail("invalid_unit", "at is not a reading unit id");
  }

  const location: ReadingLocation = {
    stream_id: stream,
    catalog_sha: catalog,
    unit_id: unit,
  };
  if (location.unit_id !== null && !isReadingLocator(location)) {
    return fail("invalid_unit", "locator failed shared validation");
  }
  return { ok: true, location };
}

/**
 * 解析本站阅读 URL。接受绝对 URL 或 `/read/{stream}?catalog=&at=` 形式的相对目标；
 * 重复参数、错类型、缺字段、外部/未知目标都走明确错误路径，绝不静默回退。
 */
export function parseReadingUrl(input: string): ReadingUrlParse {
  const raw = (input ?? "").trim();
  if (raw.length === 0) return fail("unsupported_target", "empty target");

  let url: URL;
  try {
    url = new URL(raw, READING_BASE_ORIGIN);
  } catch {
    return fail("unsupported_target", "unparseable target");
  }
  if (url.origin !== READING_BASE_ORIGIN) {
    return fail("unsupported_target", `external origin ${url.origin}`);
  }

  const seen = new Set<string>();
  for (const key of url.searchParams.keys()) {
    if (!ALLOWED_PARAMS.has(key)) {
      return fail("unknown_param", `unexpected query parameter ${key}`);
    }
    if (seen.has(key)) {
      return fail("duplicate_param", `duplicate query parameter ${key}`);
    }
    seen.add(key);
  }

  const path = url.pathname.replace(/\/+$/, "");
  const match = path.match(/^\/read\/([^/]+)$/);
  if (!match) {
    if (path === "/read" || path === "") {
      return fail("missing_stream", "reading route has no stream_id");
    }
    return fail("unsupported_target", `not a reading route: ${path}`);
  }

  let stream: string;
  try {
    stream = decodeURIComponent(match[1]);
  } catch {
    return fail("invalid_stream", "stream_id is not valid percent-encoding");
  }

  return parseReadingFields({
    stream_id: stream,
    catalog_sha: url.searchParams.get("catalog"),
    unit_id: url.searchParams.get("at"),
  });
}

/** 校验任意值是否为完整 typed locator（转发 shared 契约）。 */
export function isCompleteLocator(value: unknown): value is ReadingLocator {
  return isReadingLocator(value);
}

/** snapshot（catalog）是否与期望一致；不一致是明确错误而非静默升级。 */
export function snapshotMatches(location: ReadingLocation, catalogSha: string): boolean {
  return location.catalog_sha === catalogSha;
}

/**
 * 只由校验过的字段构造本站 typed 阅读路径。缺 unit_id 时返回从首段开始的入口。
 * 非法 locator 直接抛错，绝不接受模型生成或外部 URL。
 */
export function buildReadingPath(location: ReadingLocation): string {
  if (!UUID_V7.test(location.stream_id)) throw new Error("invalid stream_id");
  if (!SHA256.test(location.catalog_sha)) throw new Error("invalid catalog_sha");
  if (location.unit_id !== null && !UNIT_ID.test(location.unit_id)) {
    throw new Error("invalid unit_id");
  }
  const params = new URLSearchParams();
  params.set("catalog", location.catalog_sha);
  if (location.unit_id !== null) params.set("at", location.unit_id);
  return `${READING_ROUTE_PREFIX}/${encodeURIComponent(location.stream_id)}?${params.toString()}`;
}

export function buildReadingUrl(locator: ReadingLocator): string {
  if (!isReadingLocator(locator)) throw new Error("invalid reading locator");
  return buildReadingPath(locator);
}

/** 在既有详情路径上附加 return token；只允许同站路径，拒绝外部目标。 */
export function withReturnToken(path: string, token: string): string {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("return target must be a same-site path");
  }
  const params = new URLSearchParams();
  params.set(READING_RETURN_PARAM, token);
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}${params.toString()}`;
}

/**
 * 从详情 URL 的 search 读取本站 return token。显式忽略任何外部 `return_to`
 * 参数——没有 token 就没有可恢复目标，绝不据此跳转。
 */
export function readReturnToken(search: string): string | null {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const token = params.get(READING_RETURN_PARAM);
  return token && token.length > 0 ? token : null;
}

// ---------------------------------------------------------------------------
// 参考线 active-unit 选择
// ---------------------------------------------------------------------------

/** 元素在视口中的有界测量；top/bottom 为相对 viewport 的像素。 */
export interface MeasuredUnit {
  readonly unitId: string;
  readonly ordinal: number;
  readonly top: number;
  readonly bottom: number;
  readonly visible: boolean;
}

/**
 * 按 reference line 选择 active unit（reading-experience.md §4）：
 * 优先穿过参考线的 unit；落在间隙取紧随其后的可见 unit；末尾取最后一个。
 * 并列按 ordinal 升序确定；没有可见 unit 时返回 null。
 */
export function selectActiveUnit(
  units: readonly MeasuredUnit[],
  referenceLineY: number,
): MeasuredUnit | null {
  const visible = units.filter((unit) => unit.visible);
  if (visible.length === 0) return null;

  const crossing = visible
    .filter((unit) => unit.top <= referenceLineY && referenceLineY < unit.bottom)
    .sort((a, b) => a.ordinal - b.ordinal);
  if (crossing.length > 0) return crossing[0];

  const after = visible
    .filter((unit) => unit.top > referenceLineY)
    .sort((a, b) => a.top - b.top || a.ordinal - b.ordinal);
  if (after.length > 0) return after[0];

  const last = [...visible].sort((a, b) => b.bottom - a.bottom || b.ordinal - a.ordinal);
  return last[0];
}

/** unit 内相对位置（0..1），用于恢复而非按旧 scrollY 猜位置。 */
export function relativeOffsetWithin(
  unit: Pick<MeasuredUnit, "top" | "bottom">,
  referenceLineY: number,
): number {
  const height = unit.bottom - unit.top;
  if (height <= 0) return 0;
  const offset = (referenceLineY - unit.top) / height;
  return Math.min(1, Math.max(0, offset));
}

/** sticky header 下方的参考线位置，参考线在可用视口高度 30% 处。 */
export function referenceLineFor(
  viewportHeight: number,
  headerHeight: number,
  ratio = 0.3,
): number {
  const available = Math.max(0, viewportHeight - headerHeight);
  return headerHeight + available * ratio;
}

// ---------------------------------------------------------------------------
// rAF 合批
// ---------------------------------------------------------------------------

export type RequestFrame = (callback: FrameRequestCallback) => number;
export type CancelFrame = (handle: number) => void;

export interface FrameScheduler {
  schedule(task: () => void): void;
  cancel(): void;
  pending(): boolean;
}

/** 有界 rAF 合批：同一帧内多次调用只执行一次，不每个 scroll 事件扫描全文。 */
export function createFrameScheduler(
  requestFrame: RequestFrame = (callback) => requestAnimationFrame(callback),
  cancelFrame: CancelFrame = (handle) => cancelAnimationFrame(handle),
): FrameScheduler {
  let handle: number | null = null;
  return {
    schedule(task: () => void): void {
      if (handle !== null) return;
      handle = requestFrame(() => {
        handle = null;
        task();
      });
    },
    cancel(): void {
      if (handle !== null) {
        cancelFrame(handle);
        handle = null;
      }
    },
    pending(): boolean {
      return handle !== null;
    },
  };
}

// ---------------------------------------------------------------------------
// 导航状态机
// ---------------------------------------------------------------------------

export type ReadingNavigationState =
  | "idle"
  | "navigating"
  | "restoring"
  | "interrupted";

export type ReadingNavigationEvent =
  | "begin_navigation"
  | "begin_restore"
  | "user_scrolled"
  | "settled"
  | "cancelled";

/**
 * 显式导航/restoring/user-interrupted 状态转换。用户滚动打断未完成的
 * navigating/restoring；settled/cancelled 回到 idle。
 */
export function nextNavigationState(
  current: ReadingNavigationState,
  event: ReadingNavigationEvent,
): ReadingNavigationState {
  switch (event) {
    case "begin_navigation":
      return "navigating";
    case "begin_restore":
      return "restoring";
    case "user_scrolled":
      return current === "idle" ? "idle" : "interrupted";
    case "settled":
    case "cancelled":
      return "idle";
    default:
      return current;
  }
}
