#!/usr/bin/env node
// C1-T9 Playwright + Chromium visual verification (Visual: required).
//
// Boots the REAL Rust chronicle-server (embedded React build) against a
// canned C0-shaped mock upstream, then drives real Chromium over public
// Timeline/Event/Entity/Search flows plus the authenticated Studio shell.
// Writes screenshots to scripts/visual/ and fails on any missing DOM contract.
//
// Usage: node scripts/visual-verify.mjs [--base-url http://127.0.0.1:18080]
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { CAO_CAO, RED_CLIFFS, RED_CLIFFS_PLACE, startMockUpstream } from "./mock-upstream.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = join(here, "visual");
const ADMIN_USER = "admin";
const ADMIN_PASSWORD = "long-password";
// Review D-1: the server legally accepts non-control Unicode passwords, so
// the visual pass must prove a Unicode password logs in end to end.
const UNICODE_PASSWORD = "chronicle-密码-2026";
const SERVER_PORT = 18080;
const UNICODE_SERVER_PORT = 18081;

const args = process.argv.slice(2);
const baseUrlFlag = args.indexOf("--base-url");
const externalBase = baseUrlFlag >= 0 ? args[baseUrlFlag + 1] : null;

function sleep(ms) {
  return new Promise((done) => setTimeout(done, ms));
}

function spawnServer(upstreamPort, port, adminPassword) {
  const binary = join(here, "..", "..", "server", "target", "debug", "chronicle-server");
  const server = spawn(binary, [], {
    env: {
      ...process.env,
      CHRONICLE_BIND: "127.0.0.1",
      CHRONICLE_PORT: String(port),
      CHRONICLE_UPSTREAM_URL: `http://127.0.0.1:${upstreamPort}`,
      CHRONICLE_ADMIN_USER: ADMIN_USER,
      CHRONICLE_ADMIN_PASSWORD: adminPassword,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  server.stdout.on("data", (chunk) => process.stdout.write(`[server] ${chunk}`));
  server.stderr.on("data", (chunk) => process.stderr.write(`[server] ${chunk}`));
  return server;
}

async function stopServer(server) {
  if (!server) return;
  server.kill("SIGTERM");
  await sleep(500);
  server.kill("SIGKILL");
}

async function waitForHealth(base) {
  for (let i = 0; i < 100; i++) {
    try {
      const res = await fetch(`${base}/healthz`);
      if (res.ok) return;
    } catch {
      // not up yet
    }
    await sleep(100);
  }
  throw new Error(`server never became healthy: ${base}`);
}

function check(name, cond) {
  if (!cond) throw new Error(`visual verification missing ${name}`);
  console.log(`  ok: ${name}`);
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  let mock = null;
  let server = null;
  let base = externalBase;
  try {
    if (!base) {
      mock = await startMockUpstream(0);
      console.log(`mock upstream on 127.0.0.1:${mock.port}`);
      server = spawnServer(mock.port, SERVER_PORT, ADMIN_PASSWORD);
      base = `http://127.0.0.1:${SERVER_PORT}`;
    }
    await waitForHealth(base);

    const browser = await chromium.launch();
    try {
      // --- Public: Timeline (also proves public bundle skips Studio chunks).
      const studioChunks = [];
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      page.on("request", (req) => {
        if (/Studio|placeholders/i.test(req.url())) studioChunks.push(req.url());
      });
      await page.goto(`${base}/timeline?from_year=208&to_year=208`, { waitUntil: "networkidle" });
      await page.getByText("赤壁之战").first().waitFor({ timeout: 10000 });
      const timelineHTML = await page.content();
      check("Red Cliffs Timeline card", timelineHTML.includes("赤壁之战"));
      check("Wudi source on Timeline", timelineHTML.includes("三国志·魏书·武帝纪"));
      check("Wuzhu source on Timeline", timelineHTML.includes("三国志·吴书·吴主传"));
      check("canonical card once", timelineHTML.split(`data-event-id="${RED_CLIFFS}"`).length - 1 === 1);
      check("public nav skips Studio chunks", studioChunks.length === 0);
      // Review D-2: public nav links must be visibly separated, not one run.
      const navBoxes = await page.locator(".site-nav a").evaluateAll((links) =>
        links.map((link) => {
          const rect = link.getBoundingClientRect();
          return { x: rect.x, width: rect.width };
        }),
      );
      check("site-nav renders three links", navBoxes.length === 3);
      const ordered = [...navBoxes].sort((a, b) => a.x - b.x);
      const gaps = ordered.slice(1).map((box, i) => box.x - (ordered[i].x + ordered[i].width));
      check("site-nav links have visible gaps", gaps.every((gap) => gap >= 8));
      await page.screenshot({ path: join(OUT, "timeline.png") });

      // --- Public: Event Detail.
      await page.goto(`${base}/events/${RED_CLIFFS}`, { waitUntil: "networkidle" });
      await page.getByText("史料与证据").waitFor({ timeout: 10000 });
      const eventHTML = await page.content();
      check("Event evidence section", eventHTML.includes("史料与证据"));
      check("Wudi evidence text", eventHTML.includes("公至赤壁，与备战，不利。"));
      check("Wuzhu evidence text", eventHTML.includes("遇于赤壁，大破曹公军。"));
      check("Cao Cao canonical link", eventHTML.includes(`/entities/${CAO_CAO}`));
      check("related event section", eventHTML.includes("相关事件"));
      await page.screenshot({ path: join(OUT, "event.png") });

      // --- Public: Entity Detail (Cao Cao).
      await page.goto(`${base}/entities/${CAO_CAO}`, { waitUntil: "networkidle" });
      await page.getByText("事件轨迹").waitFor({ timeout: 10000 });
      const entityHTML = await page.content();
      check("Cao Cao entity page", entityHTML.includes("曹操"));
      check("trajectory to Red Cliffs", entityHTML.includes("赤壁之战"));
      await page.screenshot({ path: join(OUT, "entity.png") });

      // --- Public: Entity Detail (uncertain place).
      await page.goto(`${base}/entities/${RED_CLIFFS_PLACE}`, { waitUntil: "networkidle" });
      await page.getByText("身份不确定").first().waitFor({ timeout: 10000 });
      const placeHTML = await page.content();
      check("place involvement marker", placeHTML.includes("作为地点"));
      check("uncertain identity marker", placeHTML.includes("身份不确定"));
      await page.screenshot({ path: join(OUT, "entity-place.png") });

      // --- Public: Search.
      await page.goto(`${base}/search?q=${encodeURIComponent("曹操")}`, { waitUntil: "networkidle" });
      await page.getByText("为什么命中").first().waitFor({ timeout: 10000 });
      const searchHTML = await page.content();
      check("search result Cao Cao", searchHTML.includes("曹操"));
      check("search navigation", searchHTML.includes(`/entities/${CAO_CAO}`));
      check("search provenance", searchHTML.includes("三国志·魏书·武帝纪"));
      await page.screenshot({ path: join(OUT, "search.png") });

      // --- Mobile viewport: public timeline layout.
      const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
      await mobile.goto(`${base}/timeline?from_year=208&to_year=208`, { waitUntil: "networkidle" });
      await mobile.getByText("赤壁之战").first().waitFor({ timeout: 10000 });
      await mobile.screenshot({ path: join(OUT, "timeline-mobile.png") });
      await mobile.close();

      // --- Studio: unauthenticated shell redirects to login.
      await page.goto(`${base}/studio`, { waitUntil: "networkidle" });
      await page.getByText("Studio 登录").waitFor({ timeout: 10000 });
      const loginHTML = await page.content();
      check("studio login shell", loginHTML.includes("Studio 登录"));
      await page.screenshot({ path: join(OUT, "studio-login.png") });

      // --- Studio: login with the environment-configured admin.
      await page.getByLabel("用户名").fill(ADMIN_USER);
      await page.getByLabel("密码").fill(ADMIN_PASSWORD);
      await page.getByRole("button", { name: "登录 Studio" }).click();
      await page.getByText("Studio 总览").waitFor({ timeout: 10000 });
      const homeHTML = await page.content();
      check("studio home", homeHTML.includes("Studio 总览"));
      check("studio admin identity", homeHTML.includes(ADMIN_USER));
      await page.screenshot({ path: join(OUT, "studio-home.png") });

      // --- Studio: placeholders (route-split chunks load on demand).
      await page.goto(`${base}/studio/imports`, { waitUntil: "networkidle" });
      await page.getByText("Imports").first().waitFor({ timeout: 10000 });
      check("imports placeholder", (await page.content()).includes("C1-T10"));
      await page.screenshot({ path: join(OUT, "studio-imports.png") });

      await page.goto(`${base}/studio/review`, { waitUntil: "networkidle" });
      await page.getByText("Review").first().waitFor({ timeout: 10000 });
      check("review placeholder", (await page.content()).includes("C1-T11"));
      await page.screenshot({ path: join(OUT, "studio-review.png") });

      await page.goto(`${base}/studio/sources`, { waitUntil: "networkidle" });
      await page.getByText("Sources / Corpus").first().waitFor({ timeout: 10000 });
      check("sources placeholder", (await page.content()).includes("C1-T12"));
      await page.screenshot({ path: join(OUT, "studio-sources.png") });

      // --- Studio API stays server-enforced (no creds -> 401).
      const anon = await fetch(`${base}/api/v1/studio/status`);
      check("studio API 401 without credentials", anon.status === 401);

      // --- Review D-1: Unicode Studio password logs in end to end.
      // Restart the front with a Unicode admin password and log in through
      // the real UI in a fresh tab session. With the old btoa() encoding
      // this throws InvalidCharacterError before any request is sent.
      await page.close();
      if (!externalBase) {
        await stopServer(server);
        server = spawnServer(mock.port, UNICODE_SERVER_PORT, UNICODE_PASSWORD);
        base = `http://127.0.0.1:${UNICODE_SERVER_PORT}`;
        await waitForHealth(base);
      }
      const unicodePage = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      await unicodePage.goto(`${base}/studio`, { waitUntil: "networkidle" });
      await unicodePage.getByText("Studio 登录").waitFor({ timeout: 10000 });
      await unicodePage.getByLabel("用户名").fill(ADMIN_USER);
      await unicodePage.getByLabel("密码").fill(UNICODE_PASSWORD);
      await unicodePage.getByRole("button", { name: "登录 Studio" }).click();
      await unicodePage.getByText("Studio 总览").waitFor({ timeout: 10000 });
      const unicodeHome = await unicodePage.content();
      check("unicode password studio login", unicodeHome.includes(ADMIN_USER));
      await unicodePage.screenshot({ path: join(OUT, "studio-unicode-login.png") });
      await unicodePage.close();
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
  (err) => {
    console.error(`chronicle visual verification: FAIL: ${err.message}`);
    process.exit(1);
  },
);
