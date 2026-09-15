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
  if (background.image_href) return background.image_href;
  const assetId = background.asset_id || background.asset?.asset_id;
  if (!assetId) return null;
  const query = new URLSearchParams({ version, paragraph_id: paragraphId });
  return `/api/v1/public/background-assets/${encodeURIComponent(assetId)}?${query}`;
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
    if (background.edition_version !== version) return null;
    return background;
  } catch {
    return null;
  }
}
