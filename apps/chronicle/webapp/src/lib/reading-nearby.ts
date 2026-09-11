import type { ReadingLocator, ReadingUnit } from "./reading-types";

export interface NearbyReadingEvent {
  readonly eventId: string;
  readonly name: string;
  readonly ordinal: number;
  readonly locator: ReadingLocator;
}

/** Nearby *occurrence* anchors from loaded text. Mentions and name matching cannot select a target. */
export function nearbyReadingEvents(units: readonly ReadingUnit[], activeOrdinal: number, limit = 5): NearbyReadingEvent[] {
  const byEvent = new Map<string, NearbyReadingEvent>();
  for (const unit of units) for (const segment of unit.segments) {
    if (segment.kind !== "event") continue;
    const span = segment.span;
    if (span.status !== "resolved" || span.relation !== "current" || !span.target_event_id) continue;
    const previous = byEvent.get(span.target_event_id);
    if (previous && Math.abs(previous.ordinal - activeOrdinal) <= Math.abs(unit.ordinal - activeOrdinal)) continue;
    byEvent.set(span.target_event_id, {
      eventId: span.target_event_id, name: segment.text, ordinal: unit.ordinal,
      locator: { stream_id: unit.stream_id, catalog_sha: unit.catalog_sha, unit_id: unit.unit_id },
    });
  }
  return [...byEvent.values()]
    .sort((a, b) => Math.abs(a.ordinal - activeOrdinal) - Math.abs(b.ordinal - activeOrdinal) || a.ordinal - b.ordinal)
    .slice(0, limit).sort((a, b) => a.ordinal - b.ordinal);
}
