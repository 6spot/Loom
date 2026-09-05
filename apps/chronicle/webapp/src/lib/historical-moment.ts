import type { CoveragePayload } from "./coverage-api";
import { historicalTimeParams, parseHistoricalTime, type HistoricalTimeSelection } from "./historical-time";
import type { ClaimWrapper, ReaderPresentation } from "./types";

export interface HistoricalMomentClaim extends ClaimWrapper {
  source?: { title?: string | null; ref?: string | null };
}

export interface HistoricalMomentSource {
  bundle: string;
  ref?: string | null;
  title?: string | null;
}

export interface HistoricalMomentTime {
  status: "unknown" | "single_observed_year" | "source_disagreement";
  observed_years: number[];
  start_year: number | null;
  end_year: number | null;
  observations: Array<{
    bundle: string;
    ref: string;
    normalized_year: number | null;
    source_time: Record<string, unknown> | null;
  }>;
}

export interface HistoricalMomentEvent {
  canonical_event_id: string;
  display?: { title?: string; type?: string };
  time: HistoricalMomentTime;
  representation_count: number;
  source_count: number;
  sources: HistoricalMomentSource[];
  claims: HistoricalMomentClaim[];
  reader_presentation?: ReaderPresentation | null;
}

export interface HistoricalMomentEntityRelation {
  canonical_event_id: string;
  participant_roles: string[];
  as_place: boolean;
  claim_refs: Array<{ bundle: string; ref: string }>;
}

export interface HistoricalMomentEntity {
  canonical_entity_id: string;
  display?: { name?: string; type?: string };
  representation_count: number;
  source_count: number;
  relations: HistoricalMomentEntityRelation[];
  reader_presentation?: ReaderPresentation | null;
}

export interface HistoricalMomentResponse {
  schema: "chronicle.historical-moment";
  version: string;
  authority: {
    kind: "derived_projection";
    historical_world_state: false;
    historical_truth: false;
    mutates_history: false;
    publication_boundary: "latest_canonical_catalog";
    limitation: string;
  };
  query: {
    kind: "year" | "period";
    year: number | null;
    from_year: number;
    to_year: number;
    limit: number;
    offset: number;
  };
  catalog: { status: "published" | "unknown"; latest_catalog_sha256: string | null };
  page: { total_events: number; returned_events: number; has_more: boolean };
  events: HistoricalMomentEvent[];
  entities: HistoricalMomentEntity[];
  places: HistoricalMomentEntity[];
  polities: HistoricalMomentEntity[];
  sources: HistoricalMomentSource[];
  uncertainty: {
    temporal_disagreement_event_count: number;
    unresolved_entity_reference_count: number;
    unresolved_entity_references: unknown[];
    absence_is_not_historical_absence: true;
  };
  coverage: CoveragePayload;
}

export function historicalMomentPath(selection: HistoricalTimeSelection, limit = 100): string {
  const params = historicalTimeParams(selection);
  params.set("limit", String(limit));
  params.set("offset", "0");
  return `/api/v1/public/historical-moment?${params.toString()}`;
}

export function historicalMomentPathFromSearch(search: string): string | null {
  const selection = parseHistoricalTime(search);
  return selection ? historicalMomentPath(selection) : null;
}
