#!/usr/bin/env node
// C3-T14 real T13 person-history browser check.
//
// This driver consumes a published person-history version from the public
// API, follows the real history -> person route when a main locator is given,
// and saves the responsive screenshots used during review. It deliberately
// does not manufacture a biography fixture in the browser.

import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "@playwright/test";

function flag(name) {
  const args = process.argv.slice(2);
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : null;
}

const baseUrl = (flag("--base-url") || "").replace(/\/+$/, "");
const personId = flag("--person");
const mainVersion = flag("--main-version");
const paragraphId = flag("--paragraph");
const phaseId = flag("--phase");
const requestedPersonVersion = flag("--person-version");
const output = flag("--output") || ".artifacts/person-history-page-smoke";

if (!baseUrl || !personId) {
  console.error("person-history-page-smoke: FAIL: --base-url and --person are required");
  process.exit(2);
}
if (Boolean(mainVersion) !== Boolean(paragraphId)) {
  console.error("person-history-page-smoke: FAIL: --main-version and --paragraph must be supplied together");
  process.exit(2);
}

mkdirSync(output, { recursive: true });
const checks = [];
const apiResponses = [];

function check(name, condition, detail = "") {
  const result = { name, ok: Boolean(condition) };
  if (!result.ok && detail) result.detail = detail;
  checks.push(result);
  if (!result.ok) throw new Error(`${name}: ${detail || "condition failed"}`);
}

async function getJson(path) {
  const url = `${baseUrl}${path}`;
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  apiResponses.push({ path, status: response.status });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return body;
}

function noHorizontalOverflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth && document.body.scrollWidth <= window.innerWidth);
}

async function waitForReading(page) {
  await page.waitForSelector('[data-test="person-history-page"]', { state: "visible", timeout: 30_000 });
  await page.waitForSelector('[data-test="entity-left"]', { state: "visible", timeout: 30_000 });
  await page.waitForSelector('[data-test="entity-main"]', { state: "visible", timeout: 30_000 });
  await page.waitForSelector('[data-test="entity-right"]', { state: "visible", timeout: 30_000 });
  await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});
}

async function main() {
  const directMetadataPath = `/api/v1/public/entities/${encodeURIComponent(personId)}/history${requestedPersonVersion ? `?person_version=${encodeURIComponent(requestedPersonVersion)}` : ""}`;
  const metadata = await getJson(directMetadataPath);
  check("T13 metadata identifies the requested person", metadata.person_id === personId, `got ${metadata.person_id}`);
  const publication = metadata.publication;
  const personVersion = publication?.person_history_version || requestedPersonVersion;
  check("T13 publishes an independent person version", Boolean(personVersion && /^[0-9a-f]{64}$/.test(personVersion)), "missing person_history_version");
  if (publication) {
    check("T13 publication remains explicitly non-exhaustive", publication.coverage?.exhaustive === false, "coverage.exhaustive is not false");
    check("T13 publication exposes the four Zhou Yu reading phases or its current phase set", Array.isArray(publication.phases) && publication.phases.length >= 1, "no phases");
  }

  const entityUrl = new URL(`/entities/${encodeURIComponent(personId)}`, baseUrl);
  if (publication) entityUrl.searchParams.set("person_version", personVersion);
  if (mainVersion) {
    entityUrl.searchParams.set("version", mainVersion);
    entityUrl.searchParams.set("para", paragraphId);
    if (phaseId) entityUrl.searchParams.set("phase", phaseId);
    const mappingPath = `/api/v1/public/entities/${encodeURIComponent(personId)}/history?version=${encodeURIComponent(mainVersion)}&paragraph_id=${encodeURIComponent(paragraphId)}${phaseId ? `&phase_id=${encodeURIComponent(phaseId)}` : ""}&person_version=${encodeURIComponent(personVersion)}`;
    const mapped = await getJson(mappingPath);
    check("T13 main-history mapping response is available", Boolean(mapped.publication?.main_history_mapping || mapped.publication?.mapping), "missing mapping projection");
  }

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  try {
    if (mainVersion) {
      const historyUrl = `${baseUrl}/history/${encodeURIComponent(mainVersion)}/${encodeURIComponent(paragraphId)}`;
      await page.goto(historyUrl, { waitUntil: "domcontentloaded" });
      await page.waitForSelector(`[data-test="reading-context-entity"][data-canonical="${personId}"] [data-test="reading-context-view-entity"]`, { state: "visible", timeout: 30_000 });
      await page.locator(`[data-test="reading-context-entity"][data-canonical="${personId}"] [data-test="reading-context-view-entity"]`).first().focus();
      await page.keyboard.press("Enter");
      await page.waitForURL((url) => url.pathname === `/entities/${encodeURIComponent(personId)}`, { timeout: 30_000 });
    } else {
      await page.goto(entityUrl.toString(), { waitUntil: "domcontentloaded" });
    }
    await waitForReading(page);
    check("person page renders the three reading regions", await page.locator('[data-test="entity-left"]').count() === 1 && await page.locator('[data-test="entity-main"]').count() === 1 && await page.locator('[data-test="entity-right"]').count() === 1);
    check("person page pins its own version in the URL", new URL(page.url()).searchParams.get("person_version") === personVersion, page.url());
    check("experience paragraphs are visible", await page.locator('[data-test="person-history-paragraph"]').count() > 0, "no T13 paragraphs");
    check("default evidence remains closed", (await page.locator('[data-test="entity-evidence"]').getAttribute("open")) === null, "entity evidence was open");
    const visibleText = await page.locator("body").innerText();
    check("default reading hides implementation vocabulary", !/\bgrounding\b|\bpredicate\b|phase_ID|原始 JSON|Canonical Entity/.test(visibleText), "technical vocabulary leaked into the default view");
    check("action conclusions are not rendered as current states", await page.locator('[data-test="entity-phase-state"] [data-dimension="action"]').count() === 0, "action rendered in state panel");
    check("1440px layout has no horizontal overflow", await noHorizontalOverflow(page), "document exceeds viewport");
    await page.screenshot({ path: `${output}/person-1440.png`, fullPage: true });

    await page.setViewportSize({ width: 1920, height: 1000 });
    check("1920px layout has no horizontal overflow", await noHorizontalOverflow(page), "document exceeds viewport");
    await page.screenshot({ path: `${output}/person-1920.png`, fullPage: true });

    const paragraphEvidence = page.locator('details[data-test="person-history-evidence"]').first();
    if (await paragraphEvidence.count()) {
      await paragraphEvidence.locator(":scope > summary").click();
      const conclusionEvidence = paragraphEvidence.locator("details.pstate-evidence").first();
      await conclusionEvidence.locator(":scope > summary").click();
      await conclusionEvidence.locator('[data-test="entity-source-quote"]').first().waitFor({ state: "visible", timeout: 30_000 });
      check("T13 conclusion evidence opens on demand", (await conclusionEvidence.innerText()).includes("原章") || (await conclusionEvidence.innerText()).includes("依据"));
      const sourceButton = conclusionEvidence.getByRole("button", { name: "查看原章前后文" }).first();
      if (await sourceButton.count()) {
        await sourceButton.click();
        await page.locator('[data-test="chapter-source-panel"]').waitFor({ state: "visible", timeout: 30_000 });
        check("T13 evidence reaches original chapter context", await page.locator('[data-test="chapter-source-segments"]').count() > 0);
        await page.screenshot({ path: `${output}/person-evidence.png`, fullPage: true });
        await page.getByRole("button", { name: "关闭并回到正文" }).click();
      }
    }

    await page.setViewportSize({ width: 390, height: 844 });
    check("390px layout has no horizontal overflow", await noHorizontalOverflow(page), "document exceeds viewport");
    await page.screenshot({ path: `${output}/person-mobile-390.png`, fullPage: true });

    if (mainVersion) {
      const returnLink = page.getByRole("link", { name: "返回历史正文" });
      await returnLink.waitFor({ state: "visible", timeout: 10_000 });
      await returnLink.focus();
      await page.keyboard.press("Enter");
      await page.waitForURL((url) => url.pathname === `/history/${encodeURIComponent(mainVersion)}/${encodeURIComponent(paragraphId)}` && !url.search, { timeout: 30_000 });
      check("history return preserves the exact edition and paragraph", new URL(page.url()).pathname === `/history/${mainVersion}/${paragraphId}` && !new URL(page.url()).search, page.url());
    }

    const result = {
      schema: "chronicle.person-history-page-smoke",
      version: "0.1",
      task: "LM-75",
      base_url: baseUrl,
      person_id: personId,
      person_history_version: personVersion,
      main_history_locator: mainVersion ? { version: mainVersion, paragraph_id: paragraphId, phase_id: phaseId } : null,
      ok: true,
      checks,
      api_responses: apiResponses,
    };
    writeFileSync(`${output}/result.json`, `${JSON.stringify(result, null, 2)}\n`, "utf8");
    console.log(`person-history-page-smoke: PASS; ${checks.length} checks; evidence at ${output}/result.json`);
  } catch (error) {
    const result = {
      schema: "chronicle.person-history-page-smoke",
      version: "0.1",
      task: "LM-75",
      base_url: baseUrl,
      person_id: personId,
      person_history_version: personVersion,
      main_history_locator: mainVersion ? { version: mainVersion, paragraph_id: paragraphId, phase_id: phaseId } : null,
      ok: false,
      checks,
      api_responses: apiResponses,
      error: error instanceof Error ? error.message : String(error),
    };
    writeFileSync(`${output}/result.json`, `${JSON.stringify(result, null, 2)}\n`, "utf8");
    console.error(`person-history-page-smoke: FAIL; see ${output}/result.json`);
    console.error(result.error);
    process.exitCode = 1;
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});

