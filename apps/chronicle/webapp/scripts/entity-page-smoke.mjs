#!/usr/bin/env node
// LM-61 real published entity-page browser smoke.
//
// This driver deliberately accepts the immutable values from a deployed
// publication instead of loading a fixture manifest. It exercises the route
// that a reader actually uses: history paragraph -> entity -> exact phase /
// evidence -> original chapter -> same history position. Optional source
// reading arguments cover the independent `/read/{stream}` return path.

import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "@playwright/test";

function flag(name) {
  const args = process.argv.slice(2);
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : null;
}

const baseUrl = (flag("--base-url") || "").replace(/\/+$/, "");
const version = flag("--version");
const catalog = flag("--catalog");
const paragraph = flag("--paragraph");
const entity = flag("--entity");
const expectedPhase = flag("--phase");
const stateId = flag("--state-id") || "added_sunce_allegiance";
const expectedStateLabel = flag("--state-label") || "效力";
const expectedStateValue = flag("--state-value") || "孙策";
const expectedCertainty = flag("--state-certainty");
const expectedGroupLabel = flag("--group-label") || "随孙策渡江";
const expectedTimeLabel = flag("--time-label") || "年代未详";
const sourceStream = flag("--source-stream");
const sourceCatalog = flag("--source-catalog");
const sourceUnit = flag("--source-unit");
const output = flag("--output") || ".artifacts/entity-page-smoke";

const required = [
  ["--base-url", baseUrl],
  ["--version", version],
  ["--catalog", catalog],
  ["--paragraph", paragraph],
  ["--entity", entity],
];
const missing = required.filter(([, value]) => !value).map(([name]) => name);
if (missing.length) {
  console.error(`entity-page-smoke: FAIL: missing ${missing.join(", ")}`);
  process.exit(2);
}
const sourceArgs = [sourceStream, sourceCatalog, sourceUnit];
if (sourceArgs.some(Boolean) && sourceArgs.some((value) => !value)) {
  console.error("entity-page-smoke: FAIL: source reading requires --source-stream, --source-catalog and --source-unit together");
  process.exit(2);
}

mkdirSync(output, { recursive: true });
const checks = [];
const responses = [];

function check(name, condition, detail = "") {
  const result = { name, ok: Boolean(condition) };
  if (!result.ok && detail) result.detail = detail;
  checks.push(result);
  if (!result.ok) throw new Error(`${name}: ${detail || "condition failed"}`);
}

async function waitFor(page, selector) {
  await page.locator(selector).first().waitFor({ state: "visible", timeout: 20_000 });
}

async function goto(page, url) {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});
}

async function noHorizontalOverflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth && document.body.scrollWidth <= window.innerWidth);
}

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.on("response", (response) => {
    try {
      const url = new URL(response.url());
      if (url.origin === baseUrl && url.pathname.startsWith("/api/v1/public/")) {
        responses.push({ status: response.status(), path: `${url.pathname}${url.search}` });
      }
    } catch {
      // Ignore browser-internal and malformed response URLs.
    }
  });

  const historyUrl = `${baseUrl}/history/${version}/${paragraph}`;
  const entityUrl = `${baseUrl}/entities/${encodeURIComponent(entity)}?catalog=${catalog}&version=${version}&para=${encodeURIComponent(paragraph)}${expectedPhase ? `&phase=${encodeURIComponent(expectedPhase)}` : ""}`;

  try {
    await goto(page, historyUrl);
    await waitFor(page, '[data-view="history-reading"]');
    await page.locator(`[data-history-paragraph][data-unit-id="${paragraph}"]`).waitFor({ state: "visible", timeout: 20_000 });
    const historyText = await page.locator("body").innerText();
    check("history publication renders", historyText.includes("周瑜"), "target history paragraph did not render");

    const contextEntity = page.locator(`[data-test="reading-context-entity"][data-canonical="${entity}"] [data-test="reading-context-view-entity"]`).first();
    await contextEntity.waitFor({ state: "visible", timeout: 20_000 });
    await contextEntity.focus();
    await page.keyboard.press("Enter");
    await page.waitForURL((url) => url.pathname === `/entities/${encodeURIComponent(entity)}`, { timeout: 20_000 });
    await waitFor(page, '[data-test="entity-reader-summary"]');
    await waitFor(page, '[data-test="entity-phase-state"]');

    const phasePanel = page.locator('[data-test="entity-phase-state"]');
    const phaseId = await phasePanel.getAttribute("data-phase-id");
    const paragraphId = await phasePanel.getAttribute("data-paragraph-id");
    check("entity phase is resolved from returned paragraph", paragraphId === paragraph && Boolean(phaseId), `got paragraph=${paragraphId}, phase=${phaseId}`);
    if (expectedPhase) check("URL phase cannot override paragraph phase", phaseId === expectedPhase, `expected ${expectedPhase}, got ${phaseId}`);
    check("phase has readable context", (await phasePanel.innerText()).includes("当前阶段状态"), "phase heading is missing");
    const phaseText = await phasePanel.innerText();
    const stateFact = page.locator(`[data-test="entity-phase-facts"] [data-fact-id="${stateId}"]`).first();
    check("phase renders reviewed fact", phaseText.includes(expectedStateLabel) && phaseText.includes(expectedStateValue) && await stateFact.count() === 1, "expected reviewed state fact is missing");
    if (expectedCertainty) check("phase preserves fact certainty", await stateFact.getAttribute("data-certainty") === expectedCertainty, `expected ${expectedCertainty}, got ${await stateFact.getAttribute("data-certainty")}`);
    check("phase renders readable time/group", phaseText.includes(expectedGroupLabel) && phaseText.includes(expectedTimeLabel), "group label or time label is missing");

    const entityText = await page.locator("body").innerText();
    check("default reader view hides internal locators", !/\bhp_[0-9a-f]{24}\b|\bp_[a-z0-9_]+\b/.test(entityText), "internal paragraph or phase id leaked into reader text");
    check("default reader view hides implementation vocabulary", !/grounding|canonical|predicate|Resolution/.test(entityText), "technical vocabulary leaked into reader text");
    const evidence = page.locator('[data-test="entity-evidence"]');
    check("evidence is collapsed by default", (await evidence.getAttribute("open")) === null, "evidence details opened on initial render");
    check("experience timeline is visible by default", await page.locator('[data-test="entity-experience-entry"]').count() > 0, "published experiences are missing from the reader surface");
    check("legacy event cards stay out of the reader surface", !(await evidence.locator('[data-test="trajectory-event"]').first().isVisible()), "legacy event cards are visible on the person page");
    await page.screenshot({ path: `${output}/entity-desktop.png`, fullPage: true });

    await evidence.locator(":scope > summary").click();
    check("evidence opens on demand", (await evidence.getAttribute("open")) !== null, "evidence details did not open");
    check("evidence contains source records", (await evidence.innerText()).includes("来源记录"), "source evidence is missing");
    await page.screenshot({ path: `${output}/entity-evidence-open.png`, fullPage: true });

    const stateEvidence = page.locator(`[data-test="entity-phase-facts"] [data-fact-id="${stateId}"] .entity-state-evidence`).first();
    await stateEvidence.locator("summary").click();
    await waitFor(stateEvidence, ".entity-source-quote");
    check("state evidence loads by reviewed fact id", (await stateEvidence.innerText()).includes("依据"), "state conclusion evidence did not render");
    const originalButton = stateEvidence.getByRole("button", { name: "查看原章前后文" }).first();
    await originalButton.click();
    await waitFor(page, '[data-test="chapter-source-panel"]');
    await waitFor(page, '[data-test="chapter-source-segments"]');
    check("state evidence opens original chapter context", await page.locator('[data-test="chapter-source-segments"]').count() > 0, "chapter source segments did not render");
    await page.screenshot({ path: `${output}/entity-source-context.png`, fullPage: true });
    await page.getByRole("button", { name: "关闭并回到正文" }).click();
    await page.locator('[data-test="chapter-source-panel"]').waitFor({ state: "hidden", timeout: 10_000 });

    const returnLink = page.getByRole("link", { name: "返回历史正文" });
    await returnLink.waitFor({ state: "visible", timeout: 10_000 });
    await returnLink.focus();
    await page.keyboard.press("Enter");
    await page.waitForURL((url) => url.pathname === `/history/${version}/${paragraph}` && url.search === "", { timeout: 20_000 });
    check("return preserves exact history position", new URL(page.url()).pathname === `/history/${version}/${paragraph}` && new URL(page.url()).search === "", `returned to ${page.url()}`);

    await page.setViewportSize({ width: 390, height: 844 });
    await goto(page, entityUrl);
    await waitFor(page, '[data-test="entity-reader-summary"]');
    await waitFor(page, '[data-test="entity-phase-state"]');
    check("390px entity page has no horizontal overflow", await noHorizontalOverflow(page), "document exceeds the mobile viewport");
    await page.screenshot({ path: `${output}/entity-mobile-390.png`, fullPage: true });

    await page.setViewportSize({ width: 320, height: 844 });
    await goto(page, entityUrl);
    await waitFor(page, '[data-test="entity-reader-summary"]');
    check("320px entity page has no horizontal overflow", await noHorizontalOverflow(page), "document exceeds the narrow mobile viewport");
    await page.screenshot({ path: `${output}/entity-mobile-320.png`, fullPage: true });

    await goto(page, `${baseUrl}/entities/${encodeURIComponent(entity)}?catalog=${catalog}`);
    await waitFor(page, '[data-test="entity-reader-summary"]');
    check("direct entry has an honest empty intro", await page.locator('[data-test="entity-intro-empty"]').count() === 1, "direct person entry did not show the natural empty state");
    check("direct entry does not invent a history phase", await page.locator('[data-test="entity-phase-state"]').count() === 0, "direct person entry selected a phase without a locator");

    await goto(page, `${baseUrl}/entities/${encodeURIComponent(entity)}?catalog=${catalog}&version=not-a-version&para=${encodeURIComponent(paragraph)}`);
    await waitFor(page, '[data-test="entity-reader-summary"]');
    await waitFor(page, '[data-test="entity-phase-invalid"]');
    check("invalid history locator fails closed", await page.locator('[data-test="entity-phase-state"]').count() === 0, "invalid history locator selected a phase");

    if (sourceStream) {
      await page.setViewportSize({ width: 1440, height: 1000 });
      const sourceUrl = `${baseUrl}/read/${encodeURIComponent(sourceStream)}?catalog=${sourceCatalog}&at=${encodeURIComponent(sourceUnit)}`;
      await goto(page, sourceUrl);
      await waitFor(page, '[data-test="reading-page"]');
      await waitFor(page, `[data-test="reading-unit"][data-unit-id="${sourceUnit}"]`);
      check("source reading entry renders", (await page.locator('[data-test="reading-page"]').count()) === 1, "source reading route did not render");
      const sourceEntity = page.locator(`[data-test="reading-context-entity"][data-canonical="${entity}"] [data-test="reading-context-view-entity"]`).first();
      await sourceEntity.waitFor({ state: "visible", timeout: 20_000 });
      await sourceEntity.focus();
      await page.keyboard.press("Enter");
      await page.waitForURL((url) => url.pathname === `/entities/${encodeURIComponent(entity)}`, { timeout: 20_000 });
      await waitFor(page, '[data-test="entity-reader-summary"]');
      const sourceReturn = page.getByRole("link", { name: "返回阅读" });
      await sourceReturn.waitFor({ state: "visible", timeout: 10_000 });
      await sourceReturn.focus();
      await page.keyboard.press("Enter");
      await page.waitForURL((url) => url.pathname === `/read/${encodeURIComponent(sourceStream)}` && url.searchParams.get("catalog") === sourceCatalog && url.searchParams.get("at") === sourceUnit, { timeout: 20_000 });
      check("source reading return preserves full locator", new URL(page.url()).searchParams.get("at") === sourceUnit, `returned to ${page.url()}`);
    }

    const result = {
      schema: "chronicle.entity-page-smoke",
      version: "0.1",
      task: "LM-61",
      base_url: baseUrl,
      history_locator: { version, catalog, paragraph_id: paragraph, phase_id: expectedPhase, group_label: expectedGroupLabel, time_label: expectedTimeLabel },
      entity_id: entity,
      expected_state: { id: stateId, label: expectedStateLabel, value: expectedStateValue, certainty: expectedCertainty },
      source_locator: sourceStream ? { stream_id: sourceStream, catalog_sha: sourceCatalog, unit_id: sourceUnit } : null,
      ok: true,
      checks,
      api_responses: responses,
    };
    writeFileSync(`${output}/result.json`, `${JSON.stringify(result, null, 2)}\n`, "utf8");
    console.log(`entity-page-smoke: PASS; ${checks.length} checks; evidence at ${output}/result.json`);
  } catch (error) {
    const result = {
      schema: "chronicle.entity-page-smoke",
      version: "0.1",
      task: "LM-61",
      base_url: baseUrl,
      history_locator: { version, catalog, paragraph_id: paragraph, phase_id: expectedPhase, group_label: expectedGroupLabel, time_label: expectedTimeLabel },
      entity_id: entity,
      expected_state: { id: stateId, label: expectedStateLabel, value: expectedStateValue, certainty: expectedCertainty },
      ok: false,
      checks,
      api_responses: responses,
      error: error instanceof Error ? error.message : String(error),
    };
    writeFileSync(`${output}/result.json`, `${JSON.stringify(result, null, 2)}\n`, "utf8");
    console.error(`entity-page-smoke: FAIL; see ${output}/result.json`);
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
