#!/usr/bin/env node
// Playwright + Chromium verification for the published history/source-locator
// surface. The script boots the real Rust front against a small upstream
// fixture, so route, proxy, version-pinning, and browser behavior are tested
// together.
//
// Usage: node scripts/visual-verify.mjs [--base-url http://127.0.0.1:18080]
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import {
  CAO_CAO,
  HISTORY_PARAGRAPH,
  HISTORY_VERSION,
  READING_CATALOG,
  RED_CLIFFS,
  RED_CLIFFS_PLACE,
  UNMAPPED_EVENT,
  startMockUpstream,
} from "./mock-upstream.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = join(here, "visual");
const SERVER_PORT = 18080;
const ADMIN_USER = "admin";
const ADMIN_PASSWORD = "long-password";

const args = process.argv.slice(2);
const baseUrlFlag = args.indexOf("--base-url");
const externalBase = baseUrlFlag >= 0 ? args[baseUrlFlag + 1] : null;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function spawnServer(upstreamPort, port, password) {
  const binary = join(here, "..", "..", "server", "target", "debug", "chronicle-server");
  const server = spawn(binary, [], {
    env: {
      ...process.env,
      CHRONICLE_BIND: "127.0.0.1",
      CHRONICLE_PORT: String(port),
      CHRONICLE_UPSTREAM_URL: `http://127.0.0.1:${upstreamPort}`,
      CHRONICLE_ADMIN_USER: ADMIN_USER,
      CHRONICLE_ADMIN_PASSWORD: password,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  server.stdout.on("data", (chunk) => process.stdout.write(`[server] ${chunk}`));
  server.stderr.on("data", (chunk) => process.stderr.write(`[server] ${chunk}`));
  return server;
}

async function stopServer(server) {
  if (!server || server.exitCode !== null) return;
  server.kill("SIGTERM");
  await sleep(500);
  if (server.exitCode === null) server.kill("SIGKILL");
}

async function waitForHealth(base) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(`${base}/healthz`);
      if (response.ok) return;
    } catch {
      // The server is still starting.
    }
    await sleep(100);
  }
  throw new Error(`server never became healthy: ${base}`);
}

function check(name, condition) {
  if (!condition) throw new Error(`visual verification missing ${name}`);
  console.log(`  ok: ${name}`);
}

function browserExecutable() {
  const preferred = process.env.CHROMIUM_PATH;
  const candidates = [preferred, chromium.executablePath(), "/usr/bin/chromium", "/usr/bin/google-chrome"];
  const playwrightPath = chromium.executablePath();
  const cacheRoot = dirname(dirname(dirname(playwrightPath)));
  if (existsSync(cacheRoot)) {
    for (const entry of readdirSync(cacheRoot).filter((item) => item.startsWith("chromium-")).sort().reverse()) {
      candidates.push(join(cacheRoot, entry, "chrome-linux", "chrome"));
      candidates.push(join(cacheRoot, entry, "chrome-linux-arm64", "chrome"));
    }
  }
  const executable = candidates.find((candidate) => candidate && existsSync(candidate));
  if (!executable) throw new Error("no Chromium executable is available for real-browser verification");
  return executable;
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  let mock = null;
  let server = null;
  let base = externalBase?.replace(/\/+$/, "") ?? null;
  try {
    if (!base) {
      mock = await startMockUpstream(0);
      console.log(`mock upstream on 127.0.0.1:${mock.port}`);
      server = spawnServer(mock.port, SERVER_PORT, ADMIN_PASSWORD);
      base = `http://127.0.0.1:${SERVER_PORT}`;
    }
    await waitForHealth(base);

    // Some CI images cache the full Chromium binary but omit Playwright's
    // optional headless-shell package. Use the available full browser so this
    // check remains a real browser run on both layouts.
    const browser = await chromium.launch({ executablePath: browserExecutable() });
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

      // Homepage -> published history -> exact event source locator.
      await page.goto(`${base}/`, { waitUntil: "networkidle" });
      await page.locator('[data-test="home-event-anchor"]').first().waitFor({ timeout: 10000 });
      const homeHref = await page.locator('[data-test="home-event-anchor"]').first().getAttribute("href");
      check("homepage event anchor is versioned", homeHref === `/history/${HISTORY_VERSION}/${HISTORY_PARAGRAPH}`);
      await page.screenshot({ path: join(OUT, "home.png") });

      await page.goto(`${base}/history/${HISTORY_VERSION}/${HISTORY_PARAGRAPH}`, { waitUntil: "networkidle" });
      await page.locator('[data-history-paragraph]').first().waitFor({ timeout: 10000 });
      const historyHTML = await page.content();
      check("published history reader", historyHTML.includes("合成正文中的赤壁之战"));
      check("history keeps the published version", historyHTML.includes(`data-version="${HISTORY_VERSION}"`));
      check("history renders person context", historyHTML.includes("曹操"));
      await page.screenshot({ path: join(OUT, "history.png") });

      const eventQuery = `catalog=${READING_CATALOG}&version=${HISTORY_VERSION}`;
      await page.goto(`${base}/events/${RED_CLIFFS}?${eventQuery}`, { waitUntil: "networkidle" });
      await page.locator('[data-test="event-source-panel"]').waitFor({ timeout: 10000 });
      const eventHTML = await page.content();
      check("event source locator", eventHTML.includes("事件来源定位"));
      check("event has exact published location", eventHTML.includes(`/history/${HISTORY_VERSION}/${HISTORY_PARAGRAPH}`));
      check("event keeps Wudi source", eventHTML.includes("三国志·魏书·武帝纪"));
      check("event keeps Wuzhu source", eventHTML.includes("三国志·吴书·吴主传"));
      check("event keeps source excerpts", eventHTML.includes("公至赤壁，与备战，不利。") && eventHTML.includes("遇于赤壁，大破曹公军。"));
      check("event retires encyclopedia cards", !eventHTML.includes("史料与证据") && !eventHTML.includes("Reader Presentation"));
      await page.screenshot({ path: join(OUT, "event-source-locator.png") });

      const sourceButton = page.locator('[data-test="event-source-original-entry"]').first();
      await sourceButton.click();
      await page.locator('[data-test="chapter-source-panel"]').waitFor({ timeout: 10000 });
      check("event source opens original entry", (await page.locator('[data-test="chapter-source-segments"]').count()) > 0);
      const sourceView = page.locator('[data-test="chapter-source-view-chapter"]');
      if (await sourceView.count()) {
        await sourceView.click();
        await page.locator('[data-test="chapter-source-panel"][data-view="chapter"]').waitFor({ timeout: 10000 });
        check("event source expands to chapter", true);
      }
      await page.locator('[data-test="chapter-source-close"]').click();
      await page.locator('[data-test="chapter-source-panel"]').waitFor({ state: "detached", timeout: 10000 });
      check("source panel returns to locator", true);

      // Person search goes to the person page while preserving only published
      // context keys; place identity stays explicitly uncertain.
      await page.goto(`${base}/search?q=${encodeURIComponent("曹操")}`, { waitUntil: "networkidle" });
      await page.locator('[data-search-kind="entity"]').first().waitFor({ timeout: 10000 });
      const personSearchHTML = await page.content();
      check("person search result", personSearchHTML.includes("曹操"));
      check("person search navigation", personSearchHTML.includes(`/entities/${CAO_CAO}`));
      await page.goto(`${base}/entities/${CAO_CAO}?${eventQuery}`, { waitUntil: "networkidle" });
      await page.locator('[data-view="entity"]').waitFor({ timeout: 10000 });
      const personHTML = await page.content();
      check("person page", personHTML.includes("曹操"));
      check("person page has published context", personHTML.includes(`catalog=${READING_CATALOG}`));
      check("person page does not invent year", !personHTML.includes(`/events/${RED_CLIFFS}?year=`));

      await page.goto(`${base}/search?q=${encodeURIComponent("赤壁")}`, { waitUntil: "networkidle" });
      await page.locator('[data-search-kind="event"]').first().waitFor({ timeout: 10000 });
      const placeSearchHTML = await page.content();
      check("event search exact published mapping", placeSearchHTML.includes(`/history/${HISTORY_VERSION}/${HISTORY_PARAGRAPH}`));
      check("uncertain place search result", placeSearchHTML.includes("身份不确定") && placeSearchHTML.includes(`/entities/${RED_CLIFFS_PLACE}`));
      await page.goto(`${base}/search?q=${encodeURIComponent("无正文")}`, { waitUntil: "networkidle" });
      const unmapped = page.locator('[data-test="search-event-unmapped"]');
      await unmapped.waitFor({ timeout: 10000 });
      check("unmapped event is explicit", (await unmapped.textContent()).includes("暂无对应历史正文"));
      check("unmapped event keeps source locator", (await unmapped.locator('[data-test="search-event-source-link"]').getAttribute("href")) === `/events/${UNMAPPED_EVENT}`);
      await page.goto(`${base}/entities/${RED_CLIFFS_PLACE}?${eventQuery}`, { waitUntil: "networkidle" });
      await page.locator('[data-view="entity"]').waitFor({ timeout: 10000 });
      const placeHTML = await page.content();
      check("place evidence page", placeHTML.includes("作为地点") && placeHTML.includes("赤壁之战"));
      await page.screenshot({ path: join(OUT, "place.png") });

      const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
      await mobile.goto(`${base}/history/${HISTORY_VERSION}/${HISTORY_PARAGRAPH}`, { waitUntil: "networkidle" });
      await mobile.locator('[data-history-paragraph]').first().waitFor({ timeout: 10000 });
      const mobileWidth = await mobile.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
      check("mobile history layout stays within viewport", mobileWidth);
      await mobile.screenshot({ path: join(OUT, "history-mobile.png") });
      await mobile.close();

      // Retired browser routes resolve to typed 404s, while current nav keeps
      // the history surface as the one public entry.
      for (const path of ["/world", "/timeline"]) {
        const response = await page.request.get(`${base}${path}`);
        check(`${path} is retired`, response.status() === 404);
      }
      const navHref = await page.locator('.site-nav a').first().getAttribute("href");
      check("public nav points to history", navHref === "/history");

      // Studio remains server-authenticated after the public route cleanup.
      await page.goto(`${base}/studio`, { waitUntil: "networkidle" });
      await page.getByText("管理工作台登录").waitFor({ timeout: 10000 });
      await page.getByLabel("用户名").fill(ADMIN_USER);
      await page.getByLabel("密码").fill(ADMIN_PASSWORD);
      await page.getByRole("button", { name: "登录管理工作台" }).click();
      await page.getByRole("heading", { name: "内容工作台" }).waitFor({ timeout: 10000 });
      check("Studio remains reachable after public cleanup", (await page.locator('[data-view="studio-home"]').count()) === 1);
      await page.screenshot({ path: join(OUT, "studio-home.png") });

      await page.close();
    } finally {
      await browser.close();
    }
    console.log(`chronicle visual verification: PASS (screenshots in ${OUT})`);
  } finally {
    await stopServer(server);
    if (mock) await mock.close();
  }
}

main().then(
  () => process.exit(0),
  (error) => {
    console.error(`chronicle visual verification: FAIL: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  },
);
