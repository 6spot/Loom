// C3-T16 reader boundary for saved background bindings.
//
// The reader consumes only the public background read contract owned by
// apps/chronicle/docs/background-art.md §4.3: an exact edition/paragraph read
// returns the active binding metadata or nothing. Candidates, disabled
// bindings, wrong editions/paragraphs and failed reads all fall back to the
// plain paper page; the reader never substitutes another image, never borrows
// a neighboring range and never writes a public association. Display numbers
// come from the saved binding response, not from reader-side defaults.

import type { CSSProperties } from "react";
import { fetchJSON } from "./api";

export interface HistoryBackgroundDisplay {
  opacity: number;
  position: { x: number; y: number };
  scale: number;
  mask: {
    shape?: "rect" | "gradient";
    top?: number;
    right?: number;
    bottom?: number;
    left?: number;
  } | null;
}

export interface HistoryBackgroundAsset {
  asset_id: string;
  asset_version_id: string;
  version: number;
  filename: string;
  media_type: string;
  width: number;
  height: number;
  source?: string | null;
  era?: string | null;
  resource_href?: string;
}

export interface HistoryBackground {
  binding_id: string;
  edition_version: string;
  start_paragraph_id: string;
  end_paragraph_id: string;
  start_ordinal: number;
  end_ordinal: number;
  asset_id: string;
  asset_version_id: string;
  asset_version: number;
  display: HistoryBackgroundDisplay;
  status: string;
  active: boolean;
  revision: number;
  etag: string;
  image_href?: string;
  asset: HistoryBackgroundAsset;
}

const API = "/api/v1/public/backgrounds";
const IMAGE_API = "/api/v1/public/background-assets";
const LOCAL_ORIGIN = "https://loom.local";
const HISTORY_SHA = /^[0-9a-f]{64}$/;
const HISTORY_PARAGRAPH = /^hp_[0-9a-f]{24}$/;

/** Keep metadata cache entries scoped to the immutable edition and exact paragraph. */
export function historyBackgroundQueryKey(version: string, paragraphId: string): readonly string[] {
  return ["history", "background", version, paragraphId];
}

/**
 * The reading controller already owns the active paragraph. This helper only
 * selects the two adjacent loaded paragraphs; it never observes scrolling or
 * creates another position state machine.
 */
export function historyBackgroundAdjacentParagraphIds(
  paragraphs: readonly { readonly id: string; readonly ordinal: number }[],
  activeParagraphId: string | null,
): string[] {
  if (!activeParagraphId) return [];
  const active = paragraphs.find((paragraph) => paragraph.id === activeParagraphId);
  if (!active || !Number.isSafeInteger(active.ordinal)) return [];
  const byOrdinal = new Map<number, string>();
  for (const paragraph of paragraphs) {
    if (paragraph.id && Number.isSafeInteger(paragraph.ordinal)) byOrdinal.set(paragraph.ordinal, paragraph.id);
  }
  return [-1, 1]
    .map((delta) => byOrdinal.get(active.ordinal + delta))
    .filter((id): id is string => Boolean(id) && id !== activeParagraphId);
}

export function historyBackgroundPath(version: string, paragraphId: string): string {
  return `${API}?${new URLSearchParams({ version, paragraph_id: paragraphId })}`;
}

/**
 * Bytes come from the exact binding the metadata response named. The server
 * marks the anonymous asset route with the same edition/paragraph locator, so
 * guessing an asset id cannot fetch an unsaved or out-of-range image.
 */
export function historyBackgroundImagePath(
  background: HistoryBackground,
  version: string,
  paragraphId: string,
): string | null {
  const assetId = background.asset_id || background.asset?.asset_id;
  if (!assetId) return null;
  const query = new URLSearchParams({ version, paragraph_id: paragraphId });
  const expected = `${IMAGE_API}/${encodeURIComponent(assetId)}?${query}`;
  if (!background.image_href) return expected;

  // The API may return a resource URL, but only reuse it when it is the same
  // same-origin asset and exact edition/paragraph locator. Otherwise construct
  // the checked route from the saved asset id instead of trusting a stale URL.
  try {
    const href = new URL(background.image_href, LOCAL_ORIGIN);
    const expectedUrl = new URL(expected, LOCAL_ORIGIN);
    if (href.origin !== expectedUrl.origin || href.pathname !== expectedUrl.pathname
      || href.searchParams.get("version") !== version
      || href.searchParams.get("paragraph_id") !== paragraphId) return expected;
    return background.image_href;
  } catch {
    return expected;
  }
}

function clamp(value: number, minimum: number, maximum: number, fallback: number): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.min(maximum, Math.max(minimum, value));
}

/** Reader rendering values are the saved display settings, clamped defensively. */
export function historyBackgroundStyle(display: HistoryBackgroundDisplay, visible: boolean): CSSProperties {
  const opacity = visible ? clamp(display?.opacity ?? 0, 0, 1, 0) : 0;
  const scale = clamp(display?.scale ?? 1, 0.1, 4, 1);
  const x = clamp(display?.position?.x ?? 0.5, 0, 1, 0.5);
  const y = clamp(display?.position?.y ?? 0.5, 0, 1, 0.5);
  return {
    opacity,
    objectPosition: `${x * 100}% ${y * 100}%`,
    transform: `scale(${scale})`,
  };
}

export function historyBackgroundMaskStyle(mask: NonNullable<HistoryBackgroundDisplay["mask"]>): CSSProperties {
  const edge = (value: number | undefined) => `${clamp(value ?? 0, 0, 1, 0) * 100}%`;
  return { top: edge(mask.top), right: edge(mask.right), bottom: edge(mask.bottom), left: edge(mask.left) };
}

/**
 * Preload image bytes without adding an element to the reading DOM. The
 * caller owns the abort signal so disabling backgrounds can stop pending
 * adjacent loads; a late completion is still harmless because the component
 * keys visibility by the exact image URL.
 */
export function preloadHistoryBackgroundImage(path: string, signal?: AbortSignal): Promise<void> {
  if (typeof window === "undefined" || typeof window.Image === "undefined") return Promise.resolve();
  return new Promise<void>((resolve, reject) => {
    const image = new window.Image();
    let settled = false;
    const cleanup = () => signal?.removeEventListener("abort", abort);
    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (error) reject(error);
      else resolve();
    };
    const abort = () => {
      image.src = "";
      finish(signal?.reason instanceof Error ? signal.reason : new DOMException("Background preload aborted", "AbortError"));
    };
    image.decoding = "async";
    image.onload = () => finish();
    image.onerror = () => finish(new Error("background image failed to load"));
    if (signal) {
      if (signal.aborted) {
        abort();
        return;
      }
      signal.addEventListener("abort", abort, { once: true });
    }
    image.src = path;
  });
}

/**
 * One exact public read. A missing binding (200 with `background: null`), an
 * unknown paragraph/edition (404/400), a disabled binding or any transport or
 * parse failure resolves to `null`; only a currently active binding returns
 * metadata. The reader therefore cannot show a candidate, a stale image or an
 * error state over the prose.
 */
export async function loadHistoryBackground(
  version: string,
  paragraphId: string,
  signal?: AbortSignal,
): Promise<HistoryBackground | null> {
  try {
    const payload = await fetchJSON<{ background: HistoryBackground | null }>(
      historyBackgroundPath(version, paragraphId),
      { signal },
    );
    const background = payload?.background ?? null;
    if (!background || background.active !== true || background.status !== "active") return null;
    if (background.edition_version !== version || !HISTORY_SHA.test(version)
      || !HISTORY_PARAGRAPH.test(paragraphId)
      || !HISTORY_PARAGRAPH.test(background.start_paragraph_id)
      || !HISTORY_PARAGRAPH.test(background.end_paragraph_id)
      || !background.asset_id || !background.asset_version_id) return null;
    return background;
  } catch (error) {
    // Abort is a control-flow result, not an empty binding. Re-throwing keeps
    // cancelled prefetches from poisoning the query cache with `null`.
    if (signal?.aborted) throw error;
    return null;
  }
}
