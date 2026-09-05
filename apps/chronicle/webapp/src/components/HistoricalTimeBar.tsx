import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  MAX_HISTORICAL_PERIOD_YEARS,
  historicalTimeLabel,
  isSupportedHistoricalYear,
  parseHistoricalTime,
  worldPathForSelection,
  type HistoricalTimeSelection,
} from "../lib/historical-time";

function parseInput(value: FormDataEntryValue | null): number | null {
  const text = String(value ?? "").trim();
  if (!/^-?\d+$/.test(text)) return null;
  const number = Number(text);
  return Number.isSafeInteger(number) ? number : null;
}

export default function HistoricalTimeBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const selection = parseHistoricalTime(location.search);
  const [error, setError] = useState<string | null>(null);
  const start = selection?.kind === "year" ? selection.year : selection?.fromYear;
  const end = selection?.kind === "period" ? selection.toYear : "";

  const moveYear = (delta: number) => {
    if (!selection || selection.kind !== "year") return;
    const next = selection.year + delta;
    if (isSupportedHistoricalYear(next)) navigate(worldPathForSelection({ kind: "year", year: next }));
  };

  return (
    <section className="historical-time-bar" data-test="historical-time-bar" aria-label="全局历史时间">
      <div className="historical-time-summary">
        <span className="historical-time-kicker">历史时间</span>
        <strong>{selection ? historicalTimeLabel(selection) : "尚未选择"}</strong>
        <small>Chronicle 当前只表达年 / 年段精度，不虚构月日。</small>
      </div>
      <form
        key={`${start ?? ""}:${end}`}
        className="historical-time-form"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const fromYear = parseInput(form.get("time_start"));
          const rawEnd = String(form.get("time_end") ?? "").trim();
          const toYear = rawEnd ? parseInput(form.get("time_end")) : fromYear;
          if (fromYear === null || toYear === null || !isSupportedHistoricalYear(fromYear) || !isSupportedHistoricalYear(toYear)) {
            setError("请输入 -10000 到 10000 之间的整数年份。");
            return;
          }
          if (fromYear > toYear) {
            setError("结束年份不能早于起始年份。");
            return;
          }
          if (toYear - fromYear + 1 > MAX_HISTORICAL_PERIOD_YEARS) {
            setError(`一次最多查看 ${MAX_HISTORICAL_PERIOD_YEARS} 年。`);
            return;
          }
          const next: HistoricalTimeSelection =
            fromYear === toYear ? { kind: "year", year: fromYear } : { kind: "period", fromYear, toYear };
          setError(null);
          navigate(worldPathForSelection(next));
        }}
      >
        <button className="time-step" type="button" onClick={() => moveYear(-1)} disabled={selection?.kind !== "year"} aria-label="上一年">
          −1
        </button>
        <label>
          <span>年份 / 起始年</span>
          <input name="time_start" inputMode="numeric" defaultValue={start ?? ""} placeholder="208" aria-label="年份或起始年" />
        </label>
        <label>
          <span>结束年（可选）</span>
          <input name="time_end" inputMode="numeric" defaultValue={end} placeholder="留空表示单年" aria-label="结束年" />
        </label>
        <button className="primary-button" type="submit">进入此时刻</button>
        <button className="time-step" type="button" onClick={() => moveYear(1)} disabled={selection?.kind !== "year"} aria-label="下一年">
          +1
        </button>
      </form>
      {error ? <p className="historical-time-error" role="alert">{error}</p> : null}
    </section>
  );
}
