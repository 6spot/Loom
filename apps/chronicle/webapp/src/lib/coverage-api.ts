import { studioRequest } from "./studio-api";

export type CoverageDensity = "unrepresented" | "sparse" | "represented";

export interface CoverageCount {
  value: string;
  count: number;
}

export interface CoverageYear {
  year: number;
  event_count: number;
  source_count: number;
  density: CoverageDensity;
  event_types: CoverageCount[];
}

export interface CoverageSource {
  bundle: string;
  source_ref: string | null;
  source_title: string | null;
  canonical_entity_count: number;
  canonical_event_count: number;
  claim_count: number;
}

export interface CoveragePayload {
  schema: "chronicle.coverage";
  version: string;
  authority: {
    kind: "derived_projection";
    historical_truth: false;
    mutates_history: false;
    publication_boundary: "latest_canonical_catalog";
    absence_semantics: string;
    density_semantics: string;
    domain_semantics: string;
  };
  query: { from_year: number | null; to_year: number | null };
  catalog: {
    status: "published" | "unknown";
    latest_catalog_sha256: string | null;
    published_source_bundle_count: number;
  };
  time: {
    known_year_span: { start_year: number | null; end_year: number | null };
    unknown_time_event_count: number;
    represented_year_median_event_count: number | null;
    requested_year_count: number;
    represented_requested_year_count: number;
    unrepresented_requested_year_count: number;
    scoped_event_count: number;
    years: CoverageYear[];
  };
  sources: CoverageSource[];
  domains: {
    basis: "event.type";
    event_types: CoverageCount[];
    claim_predicates: CoverageCount[];
  };
  entities: { canonical_count: number; types: CoverageCount[] };
  events: { canonical_count: number; scoped_canonical_count: number; types: CoverageCount[] };
  claims: { published_source_claim_count: number };
  presentations: {
    entity_targets: number;
    event_targets: number;
    published_entity_targets: number;
    published_event_targets: number;
    entity_targets_without_published_presentation: number;
    event_targets_without_published_presentation: number;
  };
  review_debt: {
    open: number;
    open_resolution: number;
    resolved: number;
    dismissed: number;
  };
}

export async function getStudioCoverage(auth: string | null): Promise<CoveragePayload> {
  return studioRequest<CoveragePayload>(auth, "/api/v1/studio/coverage");
}
