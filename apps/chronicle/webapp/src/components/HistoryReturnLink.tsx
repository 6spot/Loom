import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { ReadingHistoryStore, ReadingStorage } from "../lib/reading-history";
import { HISTORY_POSITION_STRATEGY } from "../lib/history-api";

/** Fixed historical version return, isolated from the original source-reading tokens. */
export default function HistoryReturnLink({ fallback = null }: { fallback?: ReactNode }) {
  const token = new URLSearchParams(useLocation().search).get("return");
  if (!token) return fallback;
  try {
    const store = new ReadingHistoryStore(new ReadingStorage(window.sessionStorage, HISTORY_POSITION_STRATEGY.storagePrefix), { validateLocator: HISTORY_POSITION_STRATEGY.validate });
    const position = store.resolveReturn(token);
    return position ? <Link className="public-text-button" to={HISTORY_POSITION_STRATEGY.build(position)}>返回历史正文</Link> : fallback;
  } catch { return fallback; }
}
