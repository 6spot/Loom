import { describe, expect, it } from "vitest";
import {
  chapterPath,
  chaptersPath,
  formatTime,
  formatYear,
  isStudioPath,
  readPath,
  readingPath,
} from "../src/lib/routes";

describe("public URL builders", () => {

  it("builds stable chapter hrefs pinned to the publication id", () => {
    expect(chaptersPath()).toBe("/chapters");
    expect(chapterPath("00000000-0000-7000-8000-000000000000")).toBe(
      "/chapters/00000000-0000-7000-8000-000000000000",
    );
  });

  it("builds snapshot-pinned continuous reading hrefs", () => {
    expect(readPath()).toBe("/read");
    expect(readingPath("stream-1")).toBe("/read/stream-1");
    expect(readingPath("stream-1", "a".repeat(64))).toBe(`/read/stream-1?catalog=${"a".repeat(64)}`);
    expect(readingPath("stream-1", "a".repeat(64), "ru_0123456789abcdef01234567")).toBe(
      `/read/stream-1?catalog=${"a".repeat(64)}&at=ru_0123456789abcdef01234567`,
    );
  });

  it("keeps studio paths out of the public route space", () => {
    expect(isStudioPath("/studio")).toBe(true);
    expect(isStudioPath("/studio/imports")).toBe(true);
    expect(isStudioPath("/world")).toBe(false);
    expect(isStudioPath("/studioish")).toBe(false);
  });
});

describe("year formatting", () => {
  it("renders BCE/CE years and unknown time", () => {
    expect(formatYear(208)).toBe("公元 208 年");
    expect(formatYear(-221)).toBe("公元前 221 年");
    expect(formatYear(null)).toBe("年代未定");
    expect(formatTime({})).toBe("年代未定");
    expect(formatTime({ start_year: 208, end_year: 208 })).toBe("公元 208 年");
  });
});
