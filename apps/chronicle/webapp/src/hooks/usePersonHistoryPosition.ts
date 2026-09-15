import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import type { PersonHistoryParagraph } from "../lib/person-history-api";

interface PersonHistoryPositionOptions {
  readonly paragraphs: readonly PersonHistoryParagraph[];
  readonly preferredPhaseId: string | null;
}

export interface PersonHistoryPosition {
  readonly rootRef: RefObject<HTMLElement>;
  readonly activeParagraphId: string | null;
  readonly registerParagraph: (id: string, node: HTMLElement | null) => void;
  readonly scrollToParagraph: (id: string) => void;
}

/** Keep the right-hand phase panel tied to the paragraph at the reading line. */
export function usePersonHistoryPosition({ paragraphs, preferredPhaseId }: PersonHistoryPositionOptions): PersonHistoryPosition {
  const rootRef = useRef<HTMLElement>(null);
  const nodes = useRef(new Map<string, HTMLElement>());
  const [activeParagraphId, setActiveParagraphId] = useState<string | null>(null);
  const paragraphIds = useMemo(() => paragraphs.map((paragraph) => paragraph.id), [paragraphs]);

  const registerParagraph = useCallback((id: string, node: HTMLElement | null) => {
    if (node) nodes.current.set(id, node);
    else nodes.current.delete(id);
  }, []);

  const firstParagraphForPhase = useCallback((phaseId: string | null): PersonHistoryParagraph | undefined => {
    if (!phaseId) return undefined;
    return paragraphs.find((paragraph) => paragraph.phase_id === phaseId);
  }, [paragraphs]);

  const chooseNearest = useCallback(() => {
    const root = rootRef.current;
    const candidates = paragraphIds
      .map((id) => ({ id, node: nodes.current.get(id) }))
      .filter((item): item is { id: string; node: HTMLElement } => Boolean(item.node));
    if (!candidates.length) return;
    const rootTop = root?.getBoundingClientRect().top ?? 0;
    const readingLine = rootTop + Math.min(window.innerHeight * 0.28, 220);
    let best: { id: string; distance: number } | null = null;
    for (const item of candidates) {
      const rect = item.node.getBoundingClientRect();
      if (rect.bottom <= rootTop || rect.top >= window.innerHeight) continue;
      const distance = Math.abs(rect.top - readingLine);
      if (!best || distance < best.distance) best = { id: item.id, distance };
    }
    if (!best) {
      const fallback = candidates.find((item) => item.node.getBoundingClientRect().bottom > rootTop);
      if (fallback) best = { id: fallback.id, distance: 0 };
    }
    if (best) setActiveParagraphId(best.id);
  }, [paragraphIds]);

  useEffect(() => {
    const preferred = firstParagraphForPhase(preferredPhaseId);
    if (preferred) setActiveParagraphId(preferred.id);
  }, [firstParagraphForPhase, preferredPhaseId]);

  useEffect(() => {
    const preferredAnchorId = firstParagraphForPhase(preferredPhaseId)?.id ?? null;
    const observed = paragraphIds.map((id) => nodes.current.get(id)).filter((node): node is HTMLElement => Boolean(node));
    if (!observed.length) return undefined;
    if (typeof IntersectionObserver !== "undefined") {
      const observer = new IntersectionObserver((entries) => {
        // Direct entry has no historical phase context.  Do not turn the
        // first paragraph merely visible at page load into a claimed
        // "current" identity; the first user scroll establishes the reading
        // line unless T13 mapping supplied an explicit preferred phase.
        if (window.scrollY === 0 && (!preferredPhaseId || preferredAnchorId)) {
          // Keep the explicitly mapped phase selected until the first real
          // scroll.  Without a mapping, the direct page likewise avoids
          // claiming the first visible paragraph as the current identity.
          return;
        }
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => Math.abs(left.boundingClientRect.top) - Math.abs(right.boundingClientRect.top));
        if (visible[0]) {
          const paragraph = visible[0].target as HTMLElement;
          const id = paragraph.dataset.paragraphId;
          if (id) setActiveParagraphId(id);
        }
      }, { root: null, rootMargin: "-12% 0px -58% 0px", threshold: [0, 0.2, 0.6] });
      observed.forEach((node) => observer.observe(node));
      if (!preferredAnchorId && window.scrollY > 0) chooseNearest();
      const onScroll = () => {
        if (window.scrollY > 0) chooseNearest();
      };
      window.addEventListener("scroll", onScroll, { passive: true });
      return () => {
        observer.disconnect();
        window.removeEventListener("scroll", onScroll);
      };
    }
    if (!preferredAnchorId && window.scrollY > 0) chooseNearest();
    window.addEventListener("scroll", chooseNearest, { passive: true });
    window.addEventListener("resize", chooseNearest);
    return () => {
      window.removeEventListener("scroll", chooseNearest);
      window.removeEventListener("resize", chooseNearest);
    };
  }, [chooseNearest, paragraphIds, preferredPhaseId]);

  const scrollToParagraph = useCallback((id: string) => {
    const node = nodes.current.get(id);
    if (!node) return;
    setActiveParagraphId(id);
    node.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  return { rootRef, activeParagraphId, registerParagraph, scrollToParagraph };
}
