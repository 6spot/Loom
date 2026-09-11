// C2-R2-T16 reading-flow fixture manifest contract.
//
// The gate writes `chronicle.reading-flow-fixture` next to its evidence and
// passes it to `scripts/reading-flow-smoke.mjs`. A missing, empty or
// incomplete manifest fails the driver before any browser work starts, so a
// fixture/scene/manifest gap can never look like a PASS.

import { readFileSync } from "node:fs";

export const MANIFEST_SCHEMA = "chronicle.reading-flow-fixture";
export const MANIFEST_VERSION = "0.1";

const REQUIRED_STREAM_FIELDS = [
  "stream_id",
  "catalog_sha",
  "first_unit_id",
  "unit_count",
  "group_count",
];

export function validateManifest(manifest) {
  if (!manifest || typeof manifest !== "object") {
    throw new Error("reading-flow: fixture manifest must be a JSON object");
  }
  if (manifest.schema !== MANIFEST_SCHEMA) {
    throw new Error(
      `reading-flow: fixture manifest schema must be ${MANIFEST_SCHEMA}, got ${manifest.schema}`,
    );
  }
  const streams = manifest.streams;
  if (!Array.isArray(streams) || streams.length === 0) {
    throw new Error("reading-flow: fixture manifest carries no streams");
  }
  for (const stream of streams) {
    for (const field of REQUIRED_STREAM_FIELDS) {
      if (stream[field] === undefined || stream[field] === null || stream[field] === "") {
        throw new Error(`reading-flow: stream missing ${field}: ${JSON.stringify(stream)}`);
      }
    }
    if (!/^[0-9a-f]{64}$/.test(String(stream.catalog_sha))) {
      throw new Error(`reading-flow: stream catalog_sha must be 64 hex chars: ${stream.catalog_sha}`);
    }
    if (!Number.isInteger(stream.unit_count) || stream.unit_count < 1) {
      throw new Error(`reading-flow: stream unit_count must be a positive integer`);
    }
  }
  return manifest;
}

export function loadManifest(path) {
  let text;
  try {
    text = readFileSync(path, "utf8");
  } catch (error) {
    throw new Error(`reading-flow: fixture manifest is not readable: ${path}: ${error.message}`);
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error(`reading-flow: fixture manifest is not valid JSON: ${path}: ${error.message}`);
  }
  return validateManifest(parsed);
}

export function viewports(manifest) {
  const list = manifest.viewports;
  if (!Array.isArray(list) || list.length === 0) {
    throw new Error("reading-flow: fixture manifest carries no viewports");
  }
  return list;
}

export function budgets(manifest) {
  const value = manifest.budgets;
  if (!value || typeof value !== "object") {
    throw new Error("reading-flow: fixture manifest carries no performance budgets");
  }
  for (const key of ["active_to_sidebar_p95_ms", "restore_p95_ms", "max_long_task_ms"]) {
    if (typeof value[key] !== "number") {
      throw new Error(`reading-flow: budget ${key} is missing`);
    }
  }
  return value;
}

export function readingUrl(baseUrl, stream, unitId = null) {
  const url = new URL(`/read/${encodeURIComponent(stream.stream_id)}`, baseUrl);
  url.searchParams.set("catalog", stream.catalog_sha);
  if (unitId) url.searchParams.set("at", unitId);
  return url.toString();
}
