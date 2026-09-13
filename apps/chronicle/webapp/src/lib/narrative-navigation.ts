import type { NarrativeProse } from "./narrative-types";

/** Editing an entry moves/renames its axis node in the same draft. Time ranges
 * and paragraph/phase associations remain owned by their existing editors. */
export function synchronizeNarrativeNavigation(content: NarrativeProse): NarrativeProse {
  if (!content.navigation) return content;
  const positions = new Map(content.paragraphs.map((paragraph, n) => [paragraph.id, n]));
  const entries = [...new Map(content.entry_points.map((entry) => [entry.paragraph_id, entry])).values()]
    .sort((a, b) => (positions.get(a.paragraph_id) ?? -1) - (positions.get(b.paragraph_id) ?? -1));
  return { ...content, navigation: content.navigation.map((section) => {
    const start = positions.get(section.first_paragraph_id);
    const end = positions.get(section.last_paragraph_id);
    return { ...section, items: entries.filter((entry) => {
      const position = positions.get(entry.paragraph_id);
      return position !== undefined && start !== undefined && end !== undefined && start <= position && position <= end;
    }).map(({ paragraph_id, label, reason }) => ({ paragraph_id, label, reason })) };
  }) };
}
