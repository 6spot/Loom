import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("Reader Presentation public surface", () => {
  const root = new URL("..", import.meta.url).pathname;
  const component = readFileSync(`${root}src/components/ReaderPresentation.tsx`, "utf-8");
  const eventPage = readFileSync(`${root}src/pages/public/EventPage.tsx`, "utf-8");
  const entityPage = readFileSync(`${root}src/pages/public/EntityPage.tsx`, "utf-8");

  it("keeps Reader Presentation behind the entity evidence disclosure", () => {
    const reader = "<ReaderPresentation presentation={readerPresentation} />";
    expect(eventPage).toContain(reader);
    expect(entityPage).toContain(reader);
    expect(entityPage).toContain('<details className="entity-evidence"');
    expect(entityPage.indexOf("<details className=\"entity-evidence\"")).toBeLessThan(entityPage.indexOf(reader));
    expect(eventPage.indexOf(reader)).toBeLessThan(eventPage.indexOf("<h2>史料与证据</h2>"));
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
    expect(entityPage).toContain("目前没有单独的人物简介");
    expect(entityPage).toContain("不把历史片段拼成完整传记");
    for (const source of [component, eventPage, entityPage]) {
      expect(source).not.toContain("fetchJSON(");
      expect(source).not.toContain("OpenAI");
      expect(source).not.toContain("generatePresentation");
    }
  });
});
