import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  historyBackgroundImagePath,
  historyBackgroundMaskStyle,
  historyBackgroundStyle,
  loadHistoryBackground,
} from "../../lib/history-background";

/**
 * The saved background for the active composite paragraph.
 *
 * It is an independent, pointer-events-free layer fixed behind the prose:
 * it adds no height, never captures clicks or text selection and unmounts to
 * the plain paper page whenever the active paragraph has no active binding or
 * the image fails to load. A new binding/version key replaces the image
 * element, so a late load from the previous range cannot paint over the new
 * one. The single reading position stays owned by `useReadingPosition`.
 */
export default function HistoryBackground({ version, paragraphId }: { version: string; paragraphId: string | null }) {
  const query = useQuery({
    queryKey: ["history", "background", version, paragraphId],
    queryFn: ({ signal }) => loadHistoryBackground(version, paragraphId as string, signal),
    enabled: Boolean(paragraphId),
    staleTime: 30_000,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const background = paragraphId ? query.data ?? null : null;
  const imageKey = background ? `${background.binding_id}:${background.asset_version_id}` : null;
  const [loadedImage, setLoadedImage] = useState<string | null>(null);
  const [failedImage, setFailedImage] = useState<string | null>(null);
  if (!background || !imageKey || failedImage === imageKey) return null;
  const imagePath = historyBackgroundImagePath(background, version, paragraphId as string);
  if (!imagePath) return null;
  const visible = loadedImage === imageKey;
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
      onLoad={() => setLoadedImage(imageKey)}
      onError={() => setFailedImage(imageKey)}
    />
    {mask ? <span className={`history-background-mask history-background-mask-${mask.shape ?? "gradient"}`} style={historyBackgroundMaskStyle(mask)} /> : null}
  </div>;
}
