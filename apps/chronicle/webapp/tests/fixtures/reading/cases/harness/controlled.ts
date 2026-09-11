// 受控响应样例：成功 / 失败 / 迟到 / 空白。
// 仅测试使用；不访问网络，不冒充真实后端。

import type { ReadingUnit } from "../types";
import { FIXTURE_PAGE2 } from "./fixtures";

export type LoadMode = "ok" | "fail" | "late" | "blank";

export const LATE_DELAY_MS = 700;

export async function loadNextPage(mode: LoadMode): Promise<ReadingUnit[]> {
  switch (mode) {
    case "fail":
      throw new Error("harness controlled failure: upstream_limited");
    case "blank":
      return [];
    case "late":
      return await new Promise((resolve) => {
        window.setTimeout(() => resolve(FIXTURE_PAGE2), LATE_DELAY_MS);
      });
    case "ok":
    default:
      return FIXTURE_PAGE2;
  }
}
