// Real Chromium regression for the performance gate's timing probe.
// Synthetic HTTP responses test instrumentation only, never content quality.
import assert from "node:assert/strict";
import { chromium } from "@playwright/test";
import { countRequests, installLocateTimingProbe } from "./suites/performance.mjs";

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const counts = countRequests(page);
  await page.addInitScript(installLocateTimingProbe);
  await page.route("http://chronicle-timing.test/**", (route) => route.fulfill({
    status: 200, contentType: "text/html", body: "<p>timing regression</p>",
  }));
  await page.goto("http://chronicle-timing.test/");
  const observed = await page.evaluate(async () => {
    performance.clearResourceTimings();
    performance.setResourceTimingBufferSize(2);
    for (let index = 0; index < 5; index += 1) {
      await (await fetch(`/noise/${index}`, { cache: "no-store" })).text();
    }
    for (const path of [
      "/api/v1/public/reading-streams/s/units?limit=50",
      "/api/v1/public/reading-streams/s/units/u/people?catalog=c",
      "/api/v1/public/reading-streams/s/units/u/people/p/states?catalog=c",
    ]) await (await fetch(path, { cache: "no-store" })).text();
    const before = performance.now();
    await (await fetch("/api/v1/public/reading-streams/s/locate?unit_id=u", {
      cache: "no-store",
    })).text();
    // Resource records are enqueued when the response body completes.
    await new Promise((resolve) => setTimeout(resolve, 0));
    return {
      before,
      after: performance.now(),
      buffered: performance.getEntriesByType("resource").map((entry) => entry.name),
      locate: window.__r2LocateTiming.latest("u"),
      missing: window.__r2LocateTiming.latest("never-requested"),
      stale: window.__r2LocateTiming.latest("u", performance.now()),
    };
  });
  assert.equal(observed.buffered.length, 2, "the resource buffer must be full");
  assert.equal(observed.buffered.some((name) => name.includes("/locate?")), false,
    "regression must reproduce missing locate timing in the old global buffer");
  assert.ok(observed.locate, "observer must retain the actual locate response");
  assert.ok(observed.locate.startTime >= observed.before);
  assert.ok(observed.locate.responseEnd >= observed.locate.startTime);
  assert.ok(observed.locate.responseEnd <= observed.after);
  assert.equal(observed.missing, null, "missing requests must not acquire fabricated timing");
  assert.equal(observed.stale, null, "an earlier visit cannot time a new navigation to the same unit");
  assert.equal(counts.units, 1, "person summaries and details are not body pagination requests");
  assert.equal(counts.people, 1);
  assert.equal(counts.person_details, 1);
  assert.equal(counts.locate, 1);

  await page.goto("http://chronicle-timing.test/next-document");
  assert.equal(await page.evaluate(() => window.__r2LocateTiming.latest("u")), null,
    "navigation must not reuse a previous document's response timestamp");
  console.log("PASS: locate timing survives buffer overflow, rejects stale timing, and counts exact API routes");
} finally {
  await browser.close();
}
