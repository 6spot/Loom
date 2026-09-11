import type { ContextEntityView } from "./reading-types";
export interface NarrativeEvidenceRef {
  id: string; relation: "support" | "supplement" | "contradict" | "background" | "incomparable";
  attribution: string; note: string;
}
export interface NarrativeSource {
  source_id: string; publication_id: string; document_id: string; revision_id: string;
  title: string; document_title: string; chapter_text: string;
  evidence: Array<{ id: string; anchor_id: string; start: number; end: number; quote: string }>;
}
export interface NarrativeContext {
  catalog_sha: string; sources: NarrativeSource[];
  entities: Record<string, { name: string; kind: ContextEntityView["kind"] }>;
  events: Record<string, { name: string }>;
}
export interface NarrativePhase {
  id: string; label: string; year: number | null; period: string | null; basis: string[];
  relation_to_previous: "after" | "contemporary" | "uncertain";
}
export interface NarrativeFact {
  id: string; question: string; subject_id: string | null; event_id: string | null;
  dimension: "event_detail" | "office" | "title" | "allegiance" | "administration" | "control";
  phase_ids: string[]; text: string; value: string | null;
  certainty: "clear" | "uncertain"; reason: string; evidence: NarrativeEvidenceRef[];
}
export interface NarrativeFacts {
  schema: "chronicle.source-corroboration"; version: "0.1"; title: string;
  phases: NarrativePhase[]; conclusions: NarrativeFact[];
  source_relations: Array<{ left: string; right: string; relation: string; reason: string }>;
}
export interface NarrativeProse {
  schema: "chronicle.historical-narrative"; version: "0.1";
  paragraphs: Array<{ id: string; phase_id: string;
    segments: Array<{ text: string; conclusion_ids: string[]; event_id: string | null; event_relation: string | null; event_text: string | null }>;
    entities: Array<{ entity_id: string; importance: "primary" | "other" }> }>;
  entry_points: Array<{ label: string; kind: "event" | "period"; paragraph_id: string; event_id: string | null; reason: string }>;
}
export type NarrativeContent = NarrativeFacts | NarrativeProse;
export interface NarrativeReviewData {
  kind: "facts" | "prose"; candidate_sha: string; model: string; review_id: string;
  context: NarrativeContext; candidate: NarrativeContent; facts?: NarrativeFacts;
  decision: { decision: "approve" | "reject"; rationale: string; content: NarrativeContent; content_sha: string; reviewed_conclusion_ids?: string[] } | null;
}
