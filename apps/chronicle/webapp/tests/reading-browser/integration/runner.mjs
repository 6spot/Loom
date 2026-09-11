// C2-R2-T16 shared browser suite runner for the reading flow smoke.
//
// Real Chromium only: each suite operates the integrated reading page against
// the running Rust/Python/PG stack. Checks are fail-closed; the first failed
// check aborts the suite with an explicit error.

import { mkdirSync } from "node:fs";
import { join } from "node:path";

export class SuiteRunner {
  constructor(suite, outputDir) {
    this.suite = suite;
    this.outputDir = outputDir;
    this.checks = [];
    this.evidence = {};
    this.pages = [];
  }

  check(name, condition, detail = "") {
    const ok = Boolean(condition);
    this.checks.push({ name, ok, detail: ok ? "" : String(detail) });
    if (!ok) {
      throw new Error(`reading-flow ${this.suite}: FAIL: ${name}${detail ? ` (${detail})` : ""}`);
    }
    return true;
  }

  info(name, value) {
    this.evidence[name] = value;
  }

  async newPage(options = { viewport: { width: 1440, height: 900 } }) {
    const page = await this.browser.newPage(options);
    this.pages.push(page);
    return page;
  }

  async screenshot(page, name) {
    if (!this.outputDir) return;
    const dir = join(this.outputDir, this.suite);
    mkdirSync(dir, { recursive: true });
    await page.screenshot({ path: join(dir, `${name}.png`), fullPage: false });
  }

  async closePages() {
    for (const page of this.pages) {
      try {
        await page.close();
      } catch {
        /* already closed */
      }
    }
    this.pages = [];
  }
}

export function p95(samples) {
  if (samples.length === 0) return null;
  const sorted = [...samples].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1);
  return sorted[index];
}
