/**
 * "Notable movers" — the basket's largest period-over-period changes. Deliberately not
 * branded "AI insights": it is the same momentum arithmetic `RouteMap` colours corridors
 * with, in plain language. No model, no generated text, nothing here that doesn't trace
 * back to `/v1/heatmap`.
 */

import type { Mover } from "../lib/movers";
import { formatPct, formatPeriod } from "../lib/format";
import { IconTrend } from "./icons";

export function MoversPanel({ movers }: { movers: Mover[] }) {
  if (movers.length === 0) {
    return <p className="text-sm text-ink-2">Not enough history yet to compare periods.</p>;
  }
  return (
    <ul className="flex flex-col gap-3">
      {movers.map((m) => {
        const rising = m.momentumPct >= 0;
        return (
          <li key={m.routeCode} className="flex items-center gap-3 border-b border-grid pb-3 last:border-0 last:pb-0">
            <span
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                rising ? "bg-critical-soft text-critical-ink" : "bg-good-soft text-good-ink"
              }`}
            >
              <IconTrend
                width={14}
                height={14}
                style={{ transform: rising ? undefined : "scaleY(-1)" }}
              />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm text-ink">
                <span className="font-mono font-semibold">{m.routeCode}</span>{" "}
                <span className={rising ? "text-critical-ink" : "text-good-ink"}>
                  {formatPct(m.momentumPct)}
                </span>
              </p>
              <p className="truncate text-xs text-ink-2">
                vs. previous period, {formatPeriod(m.latestPeriod)}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
