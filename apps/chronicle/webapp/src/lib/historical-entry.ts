import type { TimelineItem } from "./types";
import { isSupportedHistoricalYear } from "./historical-time";

/** Each year points to a represented event; it never becomes a reader filter. */
export function historicalEntryYears(items: readonly TimelineItem[]) {
  const years = new Map<number, TimelineItem>();
  for (const item of items) {
    const start = item.time?.start_year;
    const end = item.time?.end_year;
    if (typeof start !== "number" || start !== end || !isSupportedHistoricalYear(start)) continue;
    if (item.time?.status === "source_disagreement" || years.has(start)) continue;
    years.set(start, item);
  }
  return [...years].sort(([left], [right]) => left - right).slice(0, 6);
}
