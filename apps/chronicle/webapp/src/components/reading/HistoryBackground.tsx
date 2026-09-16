import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  historyBackgroundImagePath,
  historyBackgroundMaskStyle,
  historyBackgroundQueryKey,
  historyBackgroundStyle,
  loadHistoryBackground,
  preloadHistoryBackgroundImage,
  type HistoryBackground,
} from "../../lib/history-background";

type ImageStatus = "loading" | "loaded" | "failed";
interface ImageCacheEntry {
  status: ImageStatus;
  lastUsed: number;
}

const MAX_IMAGE_CACHE_ENTRIES = 8;

/**
 * The saved background for the active composite paragraph.
 *
 * It is an independent, pointer-events-free layer fixed behind the prose:
 * it adds no height, never captures clicks or text selection and unmounts to
 * the plain paper page whenever the active paragraph has no active binding or
 * the image fails to load. A new binding/version key replaces the image
 * element, so a late load from the previous range cannot paint over the new
 * one. Metadata and image bytes for at most the two adjacent loaded
 * paragraphs are warmed through the same active position supplied by the
 * parent; this component does not observe scrolling or own a locator.
 */
export default function HistoryBackground({
  version,
  paragraphId,
  adjacentParagraphIds = [],
  enabled = true,
}: {
  version: string;
  paragraphId: string | null;
  adjacentParagraphIds?: readonly string[];
  enabled?: boolean;
}) {
  const queryClient = useQueryClient();
  const imageCacheRef = useRef(new Map<string, ImageCacheEntry>());
  const prefetchRef = useRef(new Map<string, AbortController>());
  const mountedRef = useRef(true);
  const enabledRef = useRef(enabled);
  const currentPathRef = useRef<string | null>(null);
  enabledRef.current = enabled;
  const [, setImageRevision] = useState(0);
  const adjacentIds = useMemo(() => [...new Set(adjacentParagraphIds)]
    .filter((id) => Boolean(id) && id !== paragraphId).slice(0, 2), [adjacentParagraphIds, paragraphId]);

  const rememberImage = useCallback((path: string, status: ImageStatus) => {
    const cache = imageCacheRef.current;
    cache.set(path, { status, lastUsed: Date.now() });
    if (cache.size > MAX_IMAGE_CACHE_ENTRIES) {
      const stale = [...cache.entries()]
        .sort((left, right) => left[1].lastUsed - right[1].lastUsed)
        .slice(0, cache.size - MAX_IMAGE_CACHE_ENTRIES);
      for (const [stalePath] of stale) {
        if (stalePath !== currentPathRef.current && !prefetchRef.current.has(stalePath)) cache.delete(stalePath);
      }
    }
    if (mountedRef.current) setImageRevision((revision) => revision + 1);
  }, []);

  const abortPrefetches = useCallback(() => {
    for (const [path, controller] of prefetchRef.current) {
      controller.abort();
      prefetchRef.current.delete(path);
      const cached = imageCacheRef.current.get(path);
      if (cached?.status === "loading") imageCacheRef.current.delete(path);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortPrefetches();
    };
  }, [abortPrefetches]);

  useEffect(() => {
    if (enabled) return;
    // Turning the setting off immediately stops any adjacent image work. The
    // query cache may retain already-read metadata, but no future image
    // request is started while the reader is disabled.
    abortPrefetches();
  }, [abortPrefetches, enabled]);

  useEffect(() => {
    if (!enabled || adjacentIds.length === 0) return;
    for (const adjacentId of adjacentIds) {
      const queryKey = historyBackgroundQueryKey(version, adjacentId);
      void queryClient.fetchQuery<HistoryBackground | null>({
        queryKey,
        queryFn: ({ signal }) => loadHistoryBackground(version, adjacentId, signal),
        staleTime: 30_000,
        retry: false,
      }).then((background) => {
        if (!background || !enabledRef.current) return;
        const path = historyBackgroundImagePath(background, version, adjacentId);
        if (!path) return;
        const cached = imageCacheRef.current.get(path);
        if (cached?.status === "loaded" || cached?.status === "failed" || prefetchRef.current.has(path)) return;
        const controller = new AbortController();
        prefetchRef.current.set(path, controller);
        rememberImage(path, "loading");
        return preloadHistoryBackgroundImage(path, controller.signal)
          .then(() => rememberImage(path, "loaded"))
          .catch(() => {
            if (!controller.signal.aborted) rememberImage(path, "failed");
          })
          .finally(() => {
            if (prefetchRef.current.get(path) === controller) prefetchRef.current.delete(path);
          });
      }).catch(() => {
        // A neighboring binding is an optimization. Its failure must not
        // affect the already-rendered paragraph or create a reader error.
      });
    }
  }, [adjacentIds, enabled, queryClient, rememberImage, version]);

  const query = useQuery({
    queryKey: historyBackgroundQueryKey(version, paragraphId ?? ""),
    queryFn: ({ signal }) => loadHistoryBackground(version, paragraphId as string, signal),
    enabled: enabled && Boolean(paragraphId),
    staleTime: 30_000,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const background = enabled && paragraphId ? query.data ?? null : null;
  currentPathRef.current = null;
  if (!background || !paragraphId) return null;
  const imagePath = historyBackgroundImagePath(background, version, paragraphId as string);
  if (!imagePath) return null;
  currentPathRef.current = imagePath;
  const imageKey = `${background.binding_id}:${background.asset_version_id}:${imagePath}`;
  const imageStatus = imageCacheRef.current.get(imagePath)?.status;
  if (imageStatus === "failed") return null;
  const visible = imageStatus === "loaded";
  const mask = background.display?.mask ?? null;
  return <div
    className="history-background"
    data-test="history-background"
    data-binding-id={background.binding_id}
    data-paragraph-id={paragraphId ?? ""}
    data-status={visible ? "visible" : "loading"}
    aria-hidden="true"
  >
    <img
      key={imageKey}
      className="history-background-image"
      data-test="history-background-image"
      src={imagePath}
      alt=""
      style={historyBackgroundStyle(background.display, visible)}
      onLoad={() => rememberImage(imagePath, "loaded")}
      onError={() => rememberImage(imagePath, "failed")}
    />
    <span className="history-background-safety" aria-hidden="true" />
    {mask ? <span className={`history-background-mask history-background-mask-${mask.shape ?? "gradient"}`} style={historyBackgroundMaskStyle(mask)} /> : null}
  </div>;
}
