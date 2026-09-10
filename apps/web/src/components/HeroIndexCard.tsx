/**
 * The dashboard's headline card: the latest APIx value, its month-over-month change,
 * and a sparkline over the full published history. The detailed line-vs-CPI comparison
 * (with its own table twin and keyboard nav) still lives in its own ChartPanel further
 * down the dashboard — this is a summary, not a replacement for it.
 */

import { useMemo } from "react";
import type { IndexPoint } from "../api/client";
import { formatIndex, formatPeriod } from "../lib/format";
import { computeChanges } from "../lib/seriesChange";
import { useTheme } from "../theme/ThemeContext";
import { baseOption, tooltipDefaults } from "../theme/echartsTheme";
import { EChart } from "./EChart";
import { IconPlane } from "./icons";

/**
 * A what-if elementary index relative from `/v1/method/preview` — never a published
 * statistic. Shown only as a stand-in for the headline when the real series has not
 * published (e.g. no DGCA passenger weights loaded yet), and always visibly badged.
 */
export interface HeadlinePreview {
  value: number;
  nQuotes: number;
  formula: string;
  isLoading: boolean;
}

interface HeroIndexCardProps {
  items: IndexPoint[] | undefined;
  isLoading: boolean;
  error?: unknown;
  preview?: HeadlinePreview;
}

export function HeroIndexCard({ items, isLoading, error, preview }: HeroIndexCardProps) {
  const { tokens } = useTheme();
  const changes = useMemo(() => (items === undefined ? null : computeChanges(items)), [items]);
  const latest = items?.at(-1);

  const option = useMemo(() => {
    if (items === undefined || items.length === 0) return null;
    const periods = items.map((p) => formatPeriod(p.period));
    return {
      ...baseOption(tokens),
      grid: { left: 4, right: 4, top: 10, bottom: 4 },
      xAxis: { type: "category" as const, show: false, boundaryGap: false, data: periods },
      yAxis: { type: "value" as const, show: false, scale: true },
      tooltip: { ...tooltipDefaults(tokens), trigger: "axis" as const },
      series: [
        {
          type: "line" as const,
          data: items.map((p) => p.value),
          showSymbol: false,
          lineStyle: { width: 2, color: tokens.series[0] },
          areaStyle: { color: tokens.series[0], opacity: 0.14 },
        },
      ],
    };
  }, [items, tokens]);

  const nav = useMemo(() => {
    if (items === undefined) return undefined;
    return {
      seriesCount: 1,
      pointCount: () => items.length,
      describe: (_s: number, d: number) => {
        const point = items[d];
        return point === undefined ? "" : `${formatPeriod(point.period)}: index ${formatIndex(point.value)}.`;
      },
    };
  }, [items]);

  return (
    <div className="flex h-full flex-col justify-between gap-4 rounded-2xl border border-edge bg-surface p-5 shadow-card sm:flex-row sm:items-center">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-medium text-ink-2">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-ink">
            <IconPlane width={14} height={14} />
          </span>
          India Airfare Price Index
        </div>
        {isLoading && (
          <p className="mt-3 text-sm text-ink-2" role="status">
            Loading…
          </p>
        )}
        {error !== undefined && error !== null && (
          <p className="mt-3 text-sm text-critical-ink" role="alert">
            Could not load the headline index.
          </p>
        )}
        {latest !== undefined && (
          <>
            <p className="mt-1 font-mono text-4xl font-semibold tabular-nums text-ink">
              {formatIndex(latest.value)}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
              {changes?.mom.pct !== null && changes?.mom.pct !== undefined ? (
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${
                    changes.mom.pct >= 0 ? "bg-good-soft text-good-ink" : "bg-critical-soft text-critical-ink"
                  }`}
                >
                  <span aria-hidden="true">{changes.mom.pct >= 0 ? "▲" : "▼"}</span>
                  {changes.mom.pct >= 0 ? "+" : ""}
                  {changes.mom.pct.toFixed(1)}%
                </span>
              ) : (
                <span className="text-ink-2">{changes?.mom.unavailableReason ?? "not available"}</span>
              )}
              <span className="text-ink-2">{changes?.mom.label ?? ""}</span>
            </div>
            <p className="mt-2 text-xs text-ink-2">
              {changes?.yoy.pct === null || changes?.yoy.pct === undefined
                ? `Year-over-year: ${changes?.yoy.unavailableReason ?? "not available"}`
                : `Year-over-year: ${changes.yoy.pct >= 0 ? "+" : ""}${changes.yoy.pct.toFixed(1)}%`}
            </p>
          </>
        )}

        {latest === undefined && !isLoading && (error === undefined || error === null) && (
          <>
            <p className="mt-3 text-sm text-ink-2">
              Not yet published — the national index needs a real DGCA passenger-share
              weight for at least one route before it can be computed.
            </p>
            {preview !== undefined && (
              <div className="mt-3 rounded-lg border border-dashed border-edge bg-raised p-3">
                <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent-ink">
                  PREVIEW — not a published statistic
                </span>
                {preview.isLoading ? (
                  <p className="mt-2 text-sm text-ink-2">Loading…</p>
                ) : (
                  <p className="mt-2 text-sm text-ink">
                    Elementary price relative ({preview.formula}):{" "}
                    <span className="font-mono font-semibold tabular-nums">
                      {preview.value.toFixed(3)}
                    </span>{" "}
                    <span className="text-ink-2">
                      over the last 21-day window, from {preview.nQuotes} matched fares. What-if
                      computation, no method above the elementary level applied.
                    </span>
                  </p>
                )}
              </div>
            )}
            {preview === undefined && (
              <div className="mt-3 rounded-lg border border-dashed border-critical-ink/40 bg-raised p-3">
                <span className="inline-flex items-center gap-1 rounded-full bg-critical-soft px-2 py-0.5 text-xs font-semibold text-critical-ink">
                  NO DATA — placeholder, not a statistic
                </span>
                <p className="mt-2 text-sm text-ink">
                  <span className="font-mono font-semibold tabular-nums text-ink-2 line-through">100.0</span>{" "}
                  <span className="text-ink-2">
                    shown only so this card renders something. No fare_quote rows exist yet for this
                    environment, so nothing has actually been computed — this is not a fare index value.
                    Run <code className="font-mono">make seed-synthetic</code> and{" "}
                    <code className="font-mono">make index-run</code> to replace this with a real preview.
                  </span>
                </p>
              </div>
            )}
          </>
        )}
      </div>

      {option !== null && (
        <div className="w-full sm:w-56">
          <EChart
            option={option}
            height={110}
            ariaLabel="Sparkline of the APIx headline index over its full published history"
            nav={nav}
          />
        </div>
      )}
    </div>
  );
}
