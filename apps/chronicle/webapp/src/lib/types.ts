// Chronicle public read-model shapes (subset used by the C1-T9 web UI).
// Field names mirror the C0-T10/C0-T12 contracts; the UI never invents
// historical authority beyond these payloads.

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
    evidence?: { text?: string; locator?: Record<string, unknown> };
  };
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
