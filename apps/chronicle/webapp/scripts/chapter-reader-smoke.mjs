#!/usr/bin/env node
// C2-R1-T17 chapter reader smoke (browser behavior over the REAL Rust front).
//
// Drives real Chromium against the production chronicle-server front and
// proves the full public journey: public nav -> chapter directory ->
// complete chapter -> source reference -> chapter-wide source -> back to
// text, plus direct open / refresh of /chapters* paths. API traffic goes
// through the real Rust /api/v1/public/chapters* proxy (never a Vite dev
// server or a fetch mock); the upstream behind Rust is the isolated
// fixture/real service that owns CHRONICLE_TEST_PUBLICATION_ID.
//
// Usage:
//   node apps/chronicle/webapp/scripts/chapter-reader-smoke.mjs \
//     --base-url http://127.0.0.1:18080 \
//     --publication-id "${CHRONICLE_TEST_PUBLICATION_ID:?}"
//
// Flags: --base-url <url> (required), --publication-id <uuid> (required),
//   --shots-dir <dir> (default <scripts>/chapter-reader-shots).
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
function flag(name) {
  const at = args.indexOf(name);
  return at >= 0 ? args[at + 1] : null;
}

const BASE_URL = (flag("--base-url") || "").replace(/\/+$/, "");
const PUBLICATION_ID = flag("--publication-id") || "";
const SHOTS_DIR = flag("--shots-dir") || join(here, "chapter-reader-shots");

if (!BASE_URL) {
  console.error("chapter-reader smoke: FAIL: --base-url is required (production Rust front)");
  process.exit(1);
}
if (!PUBLICATION_ID) {
  console.error(
    "chapter-reader smoke: FAIL: --publication-id is required (published id from the isolated service)",
  );
  process.exit(1);
}

const evidence = {};
function check(name, cond, extra = "") {
  if (!cond) throw new Error(`chapter-reader smoke: FAIL: missing ${name}${extra ? ` (${extra})` : ""}`);
  console.log(`  ok: ${name}`);
  evidence[name] = true;
}

async function apiJson(path) {
  const res = await fetch(`${BASE_URL}${path}`, { headers: { Accept: "application/json" } });
  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error(
      `chapter-reader smoke: FAIL: ${path} returned ${res.status} as ${contentType}, expected JSON (API must never serve the HTML shell)`,
    );
  }
  const payload = await res.json();
  return { status: res.status, payload };
}

async function main() {
  mkdirSync(SHOTS_DIR, { recursive: true });

  // 1. Rust proxy serves the directory as JSON (proves the proxy hop, not a mock).
  const directory = await apiJson("/api/v1/public/chapters?limit=50");
  check("directory-api-200-json", directory.status === 200, `status=${directory.status}`);
  check(
    "directory-lists-publication",
    Array.isArray(directory.payload.items) &&
      directory.payload.items.some((item) => item.publication_id === PUBLICATION_ID),
    "publication not in directory",
  );

  // 2. Full chapter detail: complete ordered blocks or explicit failure, never a summary.
  const detail = await apiJson(`/api/v1/public/chapters/${encodeURIComponent(PUBLICATION_ID)}`);
  check("detail-api-200-json", detail.status === 200, `status=${detail.status}`);
  const blocks = Array.isArray(detail.payload.translation_blocks)
    ? detail.payload.translation_blocks
    : [];
  check("detail-has-full-blocks", blocks.length > 0, "empty translation_blocks");
  evidence.block_count = blocks.length;
  const firstAnchor = (blocks.find((b) => Array.isArray(b.source_anchor_ids) && b.source_anchor_ids.length > 0) || {})
    .source_anchor_ids?.[0];
  if (firstAnchor) evidence.first_anchor = firstAnchor;

  // Unknown publications stay a JSON 404, never the shell.
  const unknown = await apiJson("/api/v1/public/chapters/00000000-0000-7000-8000-ffffffffffff");
  check("unknown-publication-404-json", unknown.status === 404, `status=${unknown.status}`);

  const browser = await chromium.launch();
  try {
    // 3. Desktop: public nav exposes 篇章, directory renders.
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    await page.goto(`${BASE_URL}/world?year=208`, { waitUntil: "networkidle" });
    const navLink = page.getByRole("link", { name: "篇章" });
    check("public-nav-has-chapters", (await navLink.count()) > 0);
    await navLink.first().click();
    await page.waitForURL("**/chapters", { timeout: 15000 });
    await page.waitForSelector('[data-test="chapter-index"], [data-test="chapter-index-empty"]', {
      timeout: 15000,
    });
    check("directory-renders", true);
    await page.screenshot({ path: join(SHOTS_DIR, "desktop-directory.png") });

    // 4. Directory -> full chapter: every API block renders, first to last.
    await page.goto(`${BASE_URL}/chapters/${encodeURIComponent(PUBLICATION_ID)}`, {
      waitUntil: "networkidle",
    });
    await page.waitForSelector('[data-test="chapter-reader"]', { timeout: 15000 });
    const renderedBlocks = await page.locator('[data-test="chapter-paragraph"]').count();
    check("reader-renders-all-blocks", renderedBlocks === blocks.length, `api=${blocks.length} dom=${renderedBlocks}`);
    evidence.rendered_blocks = renderedBlocks;
    // Canonical entity/event refs are plain links into existing detail pages.
    const refLinks = page.locator('[data-test="chapter-entity-link"], [data-test="chapter-event-link"]');
    if ((await refLinks.count()) > 0) {
      const href = await refLinks.first().getAttribute("href");
      check("reference-links-to-detail", href !== null && /^\/(entities|events)\//.test(href), `href=${href}`);
    }
    await page.screenshot({ path: join(SHOTS_DIR, "desktop-reader.png") });

    // 5. Reference -> pinned source -> chapter-wide source -> back to text.
    const sourceButtons = page.locator('[data-test="chapter-source-open"]');
    if ((await sourceButtons.count()) > 0) {
      await sourceButtons.first().click();
      await page.waitForSelector('[data-test="chapter-source-panel"]', { timeout: 15000 });
      await page.waitForSelector('[data-test="chapter-source-segments"]', { timeout: 15000 });
      check("source-panel-opens", true);
      await page.screenshot({ path: join(SHOTS_DIR, "desktop-source-window.png") });
      const chapterView = page.locator('[data-test="chapter-source-view-chapter"]');
      if ((await chapterView.count()) > 0) {
        await chapterView.click();
        await page.waitForSelector('[data-test="chapter-source-panel"][data-view="chapter"]', {
          timeout: 15000,
        });
        check("source-expands-to-chapter", true);
        await page.screenshot({ path: join(SHOTS_DIR, "desktop-source-chapter.png") });
      }
      await page.locator('[data-test="chapter-source-close"]').click();
      await page.waitForSelector('[data-test="chapter-source-panel"]', { state: "detached", timeout: 10000 });
      check("source-closes-back-to-text", true);
    } else {
      evidence.no_source_anchors = true;
      console.log("  note: chapter has no source anchors; source-panel steps skipped");
    }
    // Footer stays visible at the end of the full text.
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    check("reader-footer-visible", await page.locator(".site-footer").isVisible());
    await page.screenshot({ path: join(SHOTS_DIR, "desktop-reader-footer.png"), fullPage: false });
    await page.close();

    // 6. Direct open / refresh of the deep link serves the shell + reader.
    const direct = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const shellRes = await direct.goto(`${BASE_URL}/chapters/${encodeURIComponent(PUBLICATION_ID)}`, {
      waitUntil: "domcontentloaded",
    });
    check("direct-open-200", shellRes && shellRes.ok(), `status=${shellRes && shellRes.status()}`);
    await direct.waitForSelector('[data-test="chapter-reader"]', { timeout: 15000 });
    check("direct-open-renders-reader", true);
    await direct.reload({ waitUntil: "networkidle" });
    await direct.waitForSelector('[data-test="chapter-reader"]', { timeout: 15000 });
    check("refresh-renders-reader", true);
    await direct.close();

    // 7. Mobile viewport: reader stays usable.
    const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await mobile.goto(`${BASE_URL}/chapters/${encodeURIComponent(PUBLICATION_ID)}`, {
      waitUntil: "networkidle",
    });
    await mobile.waitForSelector('[data-test="chapter-reader"]', { timeout: 15000 });
    check("mobile-reader-renders", true);
    await mobile.screenshot({ path: join(SHOTS_DIR, "mobile-reader.png") });
    await mobile.close();
  } finally {
    await browser.close();
  }

  console.log(`chapter-reader smoke: PASS ${JSON.stringify(evidence)}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
