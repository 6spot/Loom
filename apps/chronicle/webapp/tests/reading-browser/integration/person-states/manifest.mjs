// C2-R3-T14 person-state flow fixture manifest contract.
//
// The third-round gate writes `chronicle.person-state-flow-fixture` next to
// its evidence and passes it to `scripts/person-state-flow-smoke.mjs`. A
// missing, empty or incomplete manifest fails the driver before any browser
// work starts, so a fixture/scene/manifest gap can never look like a PASS.

import { readFileSync } from "node:fs";

export const MANIFEST_SCHEMA = "chronicle.person-state-flow-fixture";
export const MANIFEST_VERSION = "0.1";

const REQUIRED_HISTORY_FIELDS = [
  "version",
  "catalog_sha",
  "paragraph_id",
  "phase_id",
  "entity_id",
  "state_id",
];

export function validateManifest(manifest) {
  if (!manifest || typeof manifest !== "object") {
    throw new Error("person-state: fixture manifest must be a JSON object");
  }
  if (manifest.schema !== MANIFEST_SCHEMA) {
    throw new Error(
      `person-state: fixture manifest schema must be ${MANIFEST_SCHEMA}, got ${manifest.schema}`,
    );
  }
  const history = manifest.history;
  if (!history || typeof history !== "object") {
    throw new Error("person-state: fixture manifest carries no published history");
  }
  for (const field of REQUIRED_HISTORY_FIELDS) {
    if (history[field] === undefined || history[field] === null || history[field] === "") {
      throw new Error(`person-state: history missing ${field}: ${JSON.stringify(history)}`);
    }
  }
  if (!/^[0-9a-f]{64}$/.test(String(history.catalog_sha))) {
    throw new Error("person-state: history catalog_sha must be 64 hex chars");
  }
  const source = manifest.source_person;
  if (!source || typeof source !== "object") {
    throw new Error("person-state: fixture manifest carries no source person state");
  }
  for (const field of ["stream_id", "catalog_sha", "unit_id", "person_id"]) {
    if (!source[field]) {
      throw new Error(`person-state: source_person missing ${field}`);
    }
  }
  const review = manifest.review;
  if (!review || typeof review !== "object") {
    throw new Error("person-state: fixture manifest carries no parked reviews");
  }
  if (!review.person_state_job_id) {
    throw new Error("person-state: review missing person_state_job_id");
  }
  const scale = manifest.scale;
  if (!scale || typeof scale !== "object" || !scale.stream_id) {
    throw new Error("person-state: fixture manifest carries no synthetic scale stream");
  }
  const budgets = manifest.budgets || {};
  const targetUnits = budgets.target_units || 5000;
  const targetGroups = budgets.target_groups || 1000;
  if (!Number.isInteger(scale.unit_count) || scale.unit_count < targetUnits) {
    throw new Error(`person-state: scale unit_count ${scale.unit_count} < ${targetUnits}`);
  }
  if (!Number.isInteger(scale.group_count) || scale.group_count < targetGroups) {
    throw new Error(`person-state: scale group_count ${scale.group_count} < ${targetGroups}`);
  }
  if (!Array.isArray(manifest.viewports) || manifest.viewports.length === 0) {
    throw new Error("person-state: fixture manifest carries no viewports");
  }
  for (const key of ["person_region_p95_ms", "max_long_task_ms", "mounted_max_units"]) {
    if (typeof budgets[key] !== "number") {
      throw new Error(`person-state: budget ${key} is missing`);
    }
  }
  return manifest;
}

export function loadManifest(path) {
  let text;
  try {
    text = readFileSync(path, "utf8");
  } catch (error) {
    throw new Error(`person-state: fixture manifest is not readable: ${path}: ${error.message}`);
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error(`person-state: fixture manifest is not valid JSON: ${path}: ${error.message}`);
  }
  return validateManifest(parsed);
}

export function budgets(manifest) {
  return manifest.budgets;
}

export function viewports(manifest) {
  return manifest.viewports;
}

export function historyUrl(baseUrl, history, paragraphId = null) {
  const url = new URL("/history", baseUrl);
  url.searchParams.set("version", history.version);
  url.searchParams.set("at", paragraphId || history.paragraph_id);
  return url.toString();
}

export function entityUrl(baseUrl, history) {
  const url = new URL(`/entities/${encodeURIComponent(history.entity_id)}`, baseUrl);
  url.searchParams.set("catalog", history.catalog_sha);
  url.searchParams.set("version", history.version);
  url.searchParams.set("para", history.paragraph_id);
  url.searchParams.set("phase", history.phase_id);
  return url.toString();
}

export function sourceReadingUrl(baseUrl, source) {
  const url = new URL(`/read/${encodeURIComponent(source.stream_id)}`, baseUrl);
  url.searchParams.set("catalog", source.catalog_sha);
  url.searchParams.set("at", source.unit_id);
  return url.toString();
}

export function reviewUrl(baseUrl, review, jobId) {
  const url = new URL("/studio/review", baseUrl);
  url.searchParams.set("status", "open");
  url.searchParams.set("review_scope", review.review_scope || "all");
  if (jobId) url.searchParams.set("job_id", jobId);
  return url.toString();
}
