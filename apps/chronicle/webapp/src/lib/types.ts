// Chronicle public read-model shapes (subset used by the C1 web UI).
// Field names mirror the source-grounded contracts; Reader Presentation is a
// derived projection and never replaces the Claim/evidence fields below.

export interface TimelineItem {
  canonical_event_id: string;
  display?: { title?: string; type?: string };
  time?: { start_year?: number | null; end_year?: number | null; status?: string };
  representation_count?: number;
  source_count?: number;
  source_titles?: string[];
}

export interface TimelineResponse {
  schema: string;
  version: string;
  query?: { from_year?: number | null; to_year?: number | null; limit?: number; offset?: number };
  page?: { total?: number; returned?: number; has_more?: boolean };
  items?: TimelineItem[];
}

export interface ClaimWrapper {
  bundle?: string;
  ref?: string;
  claim?: {
    predicate?: string;
    evidence?: { text?: string; source_ref?: string; locator?: Record<string, unknown> };
  };
}

export interface ReaderSupport extends ClaimWrapper {
  source?: { title?: string; ref?: string };
}

export interface ReaderPresentationBlock {
  block_id: string;
  block_kind: "overview" | "sequence" | "outcome" | "source_notes" | "uncertainty";
  epistemic_mode: "fact_summary" | "source_report" | "uncertainty";
  text: string;
  supports?: ReaderSupport[];
}

export interface ReaderPresentation {
  presentation_id: string;
  target_kind: "entity" | "event";
  canonical_id: string;
  language: "zh-CN";
  contract_version: string;
  presentation_version: number;
  status: "published";
  generator?: {
    generator_version?: string;
    model_version?: string;
    prompt_version?: string;
  };
  input_fingerprint?: string;
  content_sha256?: string;
  origin_job_id?: string | null;
  supersedes_presentation_id?: string | null;
  generated_at?: string | null;
  blocks?: ReaderPresentationBlock[];
}

export interface Representation {
  bundle?: string;
  ref?: string;
  source?: { title?: string; record?: unknown };
  event?: unknown;
  entity?: { aliases?: string[] } & Record<string, unknown>;
  claims?: ClaimWrapper[];
}

export interface Participant {
  canonical_entity_id?: string | null;
  display?: { name?: string; type?: string };
  source_roles?: { role?: string }[];
}

export interface ResolutionLink {
  decision?: string;
  confidence?: number;
  rationale?: string;
  signals?: unknown;
  left?: Record<string, string | undefined>;
  right?: Record<string, string | undefined>;
}

export interface RelatedEvent {
  type?: string;
  event?: { canonical_event_id?: string; display?: { title?: string }; time?: TimelineItem["time"] };
}

export interface EventDetail {
  schema: string;
  canonical_event_id: string;
  display?: { title?: string; type?: string };
  time?: { start_year?: number | null; end_year?: number | null };
  source_count?: number;
  reader_presentation?: ReaderPresentation | null;
  representations?: Representation[];
  participants?: Participant[];
  places?: Participant[];
  related_events?: RelatedEvent[];
  resolution_links?: ResolutionLink[];
}

export interface TrajectoryEvent {
  canonical_event_id: string;
  display?: { title?: string };
  time?: { start_year?: number | null; end_year?: number | null };
  source_involvements?: { participant_roles?: string[]; as_place?: boolean }[];
}

export interface EntityDetail {
  schema: string;
  canonical_entity_id: string;
  display?: { name?: string; type?: string };
  source_count?: number;
  representation_count?: number;
  reader_presentation?: ReaderPresentation | null;
  representations?: Representation[];
  events?: TrajectoryEvent[];
  claims?: ClaimWrapper[];
  resolution_links?: ResolutionLink[];
}

export interface SearchSurface {
  field?: string;
  match?: string;
  value?: string;
  bundle?: string;
  ref?: string;
  source_title?: string;
}

export interface SearchItem {
  kind: "event" | "entity";
  canonical_id: string;
  display?: { name?: string; title?: string; type?: string };
  time?: { start_year?: number | null; end_year?: number | null };
  representation_count?: number;
  source_count?: number;
  source_titles?: string[];
  identity_uncertain?: boolean;
  navigation_path: string;
  match?: { rank?: number; matched_surfaces?: SearchSurface[] };
}

export interface SearchResponse {
  schema: string;
  version: string;
  query?: { q?: string; kind?: string; limit?: number };
  page?: { total?: number; returned?: number; has_more?: boolean };
  items?: SearchItem[];
}
