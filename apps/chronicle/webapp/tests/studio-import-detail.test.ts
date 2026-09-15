import { describe, expect, it } from "vitest";
import { acceptedDecisionLabel } from "../src/pages/studio/StudioImportDetailPage";

describe("completed Studio acceptance receipts", () => {
  it("renders structured staged receipts as labels instead of React children", () => {
    expect(acceptedDecisionLabel({ kind: "chapter", review_output_sha256s: [] })).toBe("已接受");
    expect(acceptedDecisionLabel({ kind: "chapter", review_id: "review-1" })).toBe("已接受");
  });

  it("keeps legacy string decisions readable", () => {
    expect(acceptedDecisionLabel("accept")).toBe("已接受");
    expect(acceptedDecisionLabel("revise")).toBe("已提交修订");
    expect(acceptedDecisionLabel(null)).toBe("已记录");
  });
});
