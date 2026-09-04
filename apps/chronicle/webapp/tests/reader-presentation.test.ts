import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("Reader Presentation public surface", () => {
  const root = new URL("..", import.meta.url).pathname;
  const component = readFileSync(`${root}src/components/ReaderPresentation.tsx`, "utf-8");
  const eventPage = readFileSync(`${root}src/pages/public/EventPage.tsx`, "utf-8");
  const entityPage = readFileSync(`${root}src/pages/public/EntityPage.tsx`, "utf-8");

  it("renders Reader Presentation before source/evidence detail on Event and Entity pages", () => {
    const reader = "<ReaderPresentation presentation={readerPresentation} />";
    for (const page of [eventPage, entityPage]) {
      expect(page).toContain(reader);
      expect(page.indexOf(reader)).toBeGreaterThan(0);
    }
    expect(eventPage.indexOf(reader)).toBeLessThan(eventPage.indexOf("<h2>史料与证据</h2>"));
    expect(entityPage.indexOf(reader)).toBeLessThan(entityPage.indexOf("<h2>来源表示</h2>"));
  });

  it("keeps Claim/evidence provenance expandable instead of presenting prose as authority", () => {
    expect(component).toContain("派生的阅读文本，不是新的历史权威");
    expect(component).toContain("support.claim?.evidence");
    expect(component).toContain("依据 · {block.supports?.length ?? 0} 条 Claim");
    expect(component).toContain("<blockquote>{evidence.text}</blockquote>");
    expect(component).toContain("presentation.generator?.model_version");
  });

  it("does not request or synthesize a fallback narrative in the browser", () => {
    expect(eventPage).toContain("暂未生成经过 grounding 校验的现代中文 Reader Presentation");
    expect(entityPage).toContain("暂未生成经过 grounding 校验的现代中文 Reader Presentation");
    for (const source of [component, eventPage, entityPage]) {
      expect(source).not.toContain("fetch(");
      expect(source).not.toContain("OpenAI");
      expect(source).not.toContain("generatePresentation");
    }
  });
});
