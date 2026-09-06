/** Per-source collection status for today, and the route coverage indicator. */

import { formatCount, formatPct } from "../lib/format";
import type { CoverageResponse } from "../api/client";
import { SourceStatusBadge } from "./badges";

export function CoverageStrip({ coverage }: { coverage: CoverageResponse }) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="list" aria-label="Source status today">
      {coverage.sources.map((source) => (
        <div
          key={source.source_code}
          role="listitem"
          className="flex items-center gap-1.5 rounded-full border border-edge bg-raised px-3 py-1.5"
          title={source.reason ?? undefined}
        >
          <SourceStatusBadge status={source.status} />
          <span className="text-xs font-medium text-ink">{source.source_code}</span>
          <span className="text-xs text-ink-2">{formatCount(source.quotes_collected)} quotes</span>
        </div>
      ))}
    </div>
  );
}

const RING_RADIUS = 30;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

export function CoverageIndicator({ coverage }: { coverage: CoverageResponse }) {
  const pct = coverage.coverage_pct;
  const offset = RING_CIRCUMFERENCE * (1 - Math.min(100, Math.max(0, pct)) / 100);

  return (
    <div className="flex flex-wrap items-center gap-5">
      <svg
        width="76"
        height="76"
        viewBox="0 0 76 76"
        role="img"
        aria-label={`${formatPct(pct, false)} of the basket covered today`}
      >
        <circle cx="38" cy="38" r={RING_RADIUS} className="stroke-grid" strokeWidth="8" fill="none" />
        <circle
          cx="38"
          cy="38"
          r={RING_RADIUS}
          className="stroke-accent"
          strokeWidth="8"
          fill="none"
          strokeLinecap="round"
          strokeDasharray={RING_CIRCUMFERENCE}
          strokeDashoffset={offset}
          transform="rotate(-90 38 38)"
          style={{ transition: "stroke-dashoffset 700ms cubic-bezier(0.16,1,0.3,1)" }}
        />
        <text
          x="38"
          y="42"
          textAnchor="middle"
          className="fill-ink font-mono text-[15px] font-semibold"
        >
          {pct.toFixed(0)}%
        </text>
      </svg>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-sm text-ink-2">Route coverage today</span>
          <span className="text-sm font-medium text-ink">
            {coverage.routes_covered}/{coverage.routes_expected} routes
          </span>
        </div>
        <div
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Route coverage today"
          className="mt-2 h-2 overflow-hidden rounded-full bg-grid"
        >
          <div
            className="h-full rounded-full bg-accent transition-[width] duration-700 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
        {coverage.routes_missing.length > 0 && (
          <p className="mt-1.5 text-xs text-ink-2">Missing: {coverage.routes_missing.join(", ")}</p>
        )}
      </div>
    </div>
  );
}
