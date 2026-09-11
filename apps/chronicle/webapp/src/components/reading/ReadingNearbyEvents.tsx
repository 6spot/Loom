import type { ReadingLocator, ReadingUnit } from "../../lib/reading-types";
import { nearbyReadingEvents } from "../../lib/reading-nearby";

export default function ReadingNearbyEvents({ units, activeOrdinal, onNavigate }: {
  units: readonly ReadingUnit[];
  activeOrdinal: number;
  onNavigate: (locator: ReadingLocator) => void;
}) {
  const events = nearbyReadingEvents(units, activeOrdinal);
  if (!events.length) return null;
  return <nav className="reading-nearby" aria-label="附近事件" data-test="reading-nearby">
    <h2>附近的事</h2>
    <ol>{events.map((event) => <li key={event.eventId}>
      <button type="button" data-test="reading-nearby-anchor" data-unit-id={event.locator.unit_id}
        aria-current={event.ordinal === activeOrdinal ? "location" : undefined}
        onClick={() => onNavigate(event.locator)}>
        {event.name}{event.ordinal === activeOrdinal ? <small>正读到这里</small> : null}
      </button>
    </li>)}</ol>
  </nav>;
}
