/**
 * A StatTile-shaped card, but for the one stat that reads better as a ring than a
 * number: basket coverage for the toolbar's chosen date. Same ring geometry as
 * `CoverageIndicator`, just sized for the stat-tile row.
 */

import { formatPct } from "../lib/format";
import { revealStyle } from "../lib/revealStyle";

const RADIUS = 20;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function CoverageTile({ pct, index = 0 }: { pct: number; index?: number }) {
  const offset = CIRCUMFERENCE * (1 - Math.min(100, Math.max(0, pct)) / 100);
  return (
    <div
      className="reveal card-hover flex flex-col gap-3 rounded-2xl border border-edge bg-surface p-5 shadow-card"
      style={revealStyle(index)}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-ink-2">Coverage</p>
        <svg width="52" height="52" viewBox="0 0 52 52" role="img" aria-label={`${formatPct(pct, false)} basket coverage`}>
          <circle cx="26" cy="26" r={RADIUS} className="stroke-grid" strokeWidth="6" fill="none" />
          <circle
            cx="26"
            cy="26"
            r={RADIUS}
            className="stroke-accent"
            strokeWidth="6"
            fill="none"
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={offset}
            transform="rotate(-90 26 26)"
            style={{ transition: "stroke-dashoffset 700ms cubic-bezier(0.16,1,0.3,1)" }}
          />
        </svg>
      </div>
      <p className="font-mono text-3xl font-semibold tabular-nums text-ink">{pct.toFixed(0)}%</p>
      <p className="text-sm text-ink-2">Basket routes with data on this date</p>
    </div>
  );
}
