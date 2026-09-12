// C2-R3-T14 shared browser runner for the person-state flow smoke.
//
// Real Chromium only. Extends the second-round SuiteRunner with context
// control: each suite gets its own browser context so a viewport and (for the
// Studio queue) the administrator's HTTP Basic credentials can be applied
// without leaking them into the public reading pages.

import { SuiteRunner } from "../runner.mjs";

export { p95 } from "../runner.mjs";

export class PersonStateRunner extends SuiteRunner {
  constructor(suite, outputDir, options = {}) {
    super(suite, outputDir);
    this.contextOptions = options.contextOptions || {};
    this.contexts = [];
  }

  async newPage(options = {}) {
    const viewport = options.viewport || { width: 1440, height: 900 };
    const context = await this.browser.newContext({
      ...this.contextOptions,
      viewport,
      hasTouch: Boolean(options.hasTouch),
      reducedMotion: options.reducedMotion || "reduce",
    });
    this.contexts.push(context);
    const page = await context.newPage();
    this.pages.push(page);
    return page;
  }

  async closePages() {
    await super.closePages();
    for (const context of this.contexts) {
      try {
        await context.close();
      } catch {
        /* already closed */
      }
    }
    this.contexts = [];
  }
}
