#!/usr/bin/env node
// C2-R2-T16 integrated reading flow browser driver.
//
// Usage:
//   node apps/chronicle/webapp/scripts/reading-flow-smoke.mjs \
//     --base-url http://127.0.0.1:18080 \
//     --fixture-manifest /tmp/chronicle-r2-offline/browser-fixture-manifest.json \
//     --suite flow|accessibility|performance|all \
//     --output /tmp/chronicle-r2-browser
//
// The driver operates the real integrated `/read/{stream}` page against the
// running Rust/Python/PG stack prepared by
// `apps/chronicle/acceptance/second_round_gate.py`. It never mocks the public
// API. A missing/incomplete fixture manifest fails before launch, so a
// fixture/scene/manifest gap can never look like a PASS.

import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

import { loadManifest } from "../tests/reading-browser/integration/manifest.mjs";
import { SuiteRunner } from "../tests/reading-browser/integration/runner.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const SUITES = ["flow", "accessibility", "performance"];

function flag(name) {
  const args = process.argv.slice(2);
  const at = args.indexOf(name);
  return at >= 0 ? args[at + 1] : null;
}

const baseUrl = (flag("--base-url") || "").replace(/\/+$/, "");
const manifestPath = flag("--fixture-manifest");
const suite = flag("--suite") || "all";
const output = flag("--output") || join(HERE, "..", "..", ".artifacts", "reading-flow-smoke");

if (!baseUrl) {
  console.error("reading-flow-smoke: FAIL: --base-url is required (running stack)");
  process.exit(2);
}
if (!manifestPath || !existsSync(manifestPath)) {
  console.error("reading-flow-smoke: FAIL: --fixture-manifest must point to an existing manifest");
  process.exit(2);
}
if (suite !== "all" && !SUITES.includes(suite)) {
  console.error(`reading-flow-smoke: FAIL: --suite must be ${[...SUITES, "all"].join("|")}`);
  process.exit(2);
}

async function runSuite(name, ctx) {
  const runner = new SuiteRunner(name, ctx.outputDir);
  runner.browser = ctx.browser;
  try {
    const specPath = join(
      HERE,
      "..",
      "tests",
      "reading-browser",
      "integration",
      "suites",
      `${name}.mjs`,
    );
    if (!existsSync(specPath)) {
      throw new Error(`reading-flow ${name}: FAIL: suite_not_implemented: ${specPath}`);
    }
    const spec = await import(pathToFileURL(specPath).href);
    if (typeof spec.run !== "function") {
      throw new Error(`reading-flow ${name}: FAIL: ${specPath} must export run(ctx)`);
    }
    await spec.run({ ...ctx, runner });
    return { suite: name, ok: true, checks: runner.checks, evidence: runner.evidence };
  } catch (error) {
    return {
      suite: name,
      ok: false,
      checks: runner.checks,
      evidence: runner.evidence,
      error: error instanceof Error ? error.message : String(error),
    };
  } finally {
    await runner.closePages();
  }
}

async function main() {
  const manifest = loadManifest(manifestPath);
  mkdirSync(output, { recursive: true });
  const requested = suite === "all" ? SUITES.slice() : [suite];
  const browser = await chromium.launch();
  const results = [];
  try {
    for (const name of requested) {
      results.push(
        await runSuite(name, { baseUrl, manifest, outputDir: output, browser }),
      );
    }
  } finally {
    await browser.close();
  }

  const ok = results.every((result) => result.ok);
  const payload = {
    schema: "chronicle.reading-flow-smoke",
    version: "0.1",
    task: "C2-R2-T16",
    base_url: baseUrl,
    fixture_manifest: manifestPath,
    requested_suite: suite,
    ok,
    results,
  };
  writeFileSync(join(output, "result.json"), `${JSON.stringify(payload, null, 2)}\n`, "utf8");

  for (const result of results) {
    console.log(`  [${result.ok ? "PASS" : "FAIL"}] ${result.suite}`);
    for (const check of result.checks) {
      if (!check.ok) console.log(`      x ${check.name}: ${check.detail}`);
    }
    for (const [name, value] of Object.entries(result.evidence)) {
      console.log(`      . ${name}=${JSON.stringify(value)}`);
    }
    if (result.error) console.log(`      ! ${result.error}`);
  }
  if (!ok) {
    console.error(`reading-flow-smoke: FAIL (suite=${suite}); see ${output}/result.json`);
    process.exit(1);
  }
  console.log(`reading-flow-smoke: PASS (suite=${suite}); evidence at ${output}/result.json`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
