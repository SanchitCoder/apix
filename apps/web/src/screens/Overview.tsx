/**
 * Screen 1 — Index overview.
 *
 * Headline APIx with day/week/year changes; the main index line with the official CPI
 * air-fare series overlaid; a route-momentum map; a data-freshness strip; a coverage
 * indicator; the latest revisions; and real entry points into the export and API
 * surfaces this dashboard sits in front of.
 *
 * "Day/week" changes are not meaningful for a monthly published index (frequency is
 * fixed by config/method.yaml), so the headline reports month-over-month and
 * year-over-year instead, and states plainly when 12 months of history do not exist
 * yet rather than fabricating a daily delta for a series that has none.
 */

import { useMemo, useState } from "react";
import { BASE_URL, CPI_SERIES, HEADLINE_SERIES } from "../api/client";
import { useCoverage, useHeatmap, useIndexSeries, useRevisions, useRoutes } from "../api/hooks";
import { ChartPanel } from "../components/ChartPanel";
import { CoverageIndicator, CoverageStrip } from "../components/CoverageStrip";
import { EChart } from "../components/EChart";
import {
  IconCalendar,
  IconCode,
  IconCopy,
  IconDownload,
  IconHistory,
  IconPlane,
  IconTrend,
} from "../components/icons";
import { RouteMap } from "../components/RouteMap";
import { StatTile } from "../components/StatTile";
import { buildCorridors } from "../lib/corridors";
import { formatDate, formatIndex, formatPeriod, todayISO } from "../lib/format";
import { computeChanges } from "../lib/seriesChange";
import { useTheme } from "../theme/ThemeContext";
import { baseOption, gridDefaults, legendDefaults, timeAxis, tooltipDefaults, valueAxis } from "../theme/echartsTheme";

const EXAMPLE_REQUEST = `GET ${BASE_URL}/v1/index?series=${HEADLINE_SERIES}&freq=M`;

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-ink-2 transition-colors hover:bg-raised hover:text-accent-ink"
      aria-label="Copy request URL"
    >
      <IconCopy width={15} height={15} />
      <span className="visually-hidden">{copied ? "Copied" : "Copy"}</span>
    </button>
  );
}

export default function Overview() {
  const { tokens } = useTheme();
  const headline = useIndexSeries(HEADLINE_SERIES);
  const cpi = useIndexSeries(CPI_SERIES);
  const coverage = useCoverage(todayISO());
  const revisions = useRevisions();
  const routesWithCoords = useRoutes();
  const heatmap = useHeatmap();

  const changes = useMemo(
    () => (headline.data === undefined ? null : computeChanges(headline.data.items)),
    [headline.data],
  );
  const latest = headline.data?.items.at(-1);

  const option = useMemo(() => {
    if (headline.data === undefined || cpi.data === undefined) return null;
    const periods = headline.data.items.map((p) => formatPeriod(p.period));
    return {
      ...baseOption(tokens),
      grid: gridDefaults(),
      tooltip: tooltipDefaults(tokens),
      legend: legendDefaults(tokens),
      xAxis: { ...timeAxis(tokens), data: periods },
      yAxis: valueAxis(tokens, "Index (ref. period = 100)"),
      series: [
        {
          name: "APIx headline",
          type: "line",
          data: headline.data.items.map((p) => p.value),
          lineStyle: { width: 2, color: tokens.series[0] },
          itemStyle: { color: tokens.series[0] },
          symbolSize: 8,
          showSymbol: false,
        },
        {
          name: "Official CPI — Transport (air fare)",
          type: "line",
          data: cpi.data.items.map((p) => p.value),
          lineStyle: { width: 2, type: "dashed" as const, color: tokens.series[1] },
          itemStyle: { color: tokens.series[1] },
          symbolSize: 8,
          showSymbol: false,
        },
      ],
    };
  }, [headline.data, cpi.data, tokens]);

  const table = useMemo(() => {
    if (headline.data === undefined || cpi.data === undefined) return undefined;
    return {
      caption: "APIx headline index and official CPI air-fare series by period",
      columns: ["Period", "APIx headline", "Official CPI (air fare)", "Quotes", "Coverage"],
      rows: headline.data.items.map((p, i) => [
        formatPeriod(p.period),
        formatIndex(p.value),
        formatIndex(cpi.data.items[i]?.value ?? NaN),
        p.n_quotes.toLocaleString("en-IN"),
        p.coverage_pct === null ? "—" : `${p.coverage_pct}%`,
      ]),
    };
  }, [headline.data, cpi.data]);

  const nav =
    headline.data === undefined || cpi.data === undefined
      ? undefined
      : {
          seriesCount: 2,
          pointCount: () => headline.data.items.length,
          describe: (s: number, d: number) => {
            const point = (s === 0 ? headline.data.items : cpi.data.items)[d];
            if (point === undefined) return "";
            const seriesName = s === 0 ? "APIx headline" : "Official CPI";
            return `${seriesName}, ${formatPeriod(point.period)}: ${formatIndex(point.value)}.`;
          },
        };

  const corridors = useMemo(
    () => buildCorridors(routesWithCoords.data?.items, heatmap.data?.items),
    [routesWithCoords.data, heatmap.data],
  );
  const mapTable = useMemo(() => {
    if (corridors.length === 0) return undefined;
    return {
      caption: "Corridor momentum: change vs. previous period",
      columns: ["Corridor", "Momentum"],
      rows: corridors.map((c) => [c.code, `${c.momentumPct >= 0 ? "+" : ""}${c.momentumPct.toFixed(1)}%`]),
    };
  }, [corridors]);

  const csvUrl = `${BASE_URL}/v1/export.csv?series=${encodeURIComponent(HEADLINE_SERIES)}`;

  return (
    <div className="flex flex-col gap-6">
      <section aria-label="Headline figures" className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatTile
          index={0}
          icon={<IconPlane />}
          label="APIx headline"
          value={latest === undefined ? "…" : formatIndex(latest.value)}
          delta={changes === null ? undefined : changes.mom}
        />
        <StatTile
          index={1}
          icon={<IconCalendar />}
          label="Month-over-month"
          value={changes?.mom.pct === null || changes?.mom.pct === undefined
            ? "—"
            : `${changes.mom.pct >= 0 ? "+" : ""}${changes.mom.pct.toFixed(1)}%`}
        />
        <StatTile
          index={2}
          icon={<IconTrend />}
          label="Year-over-year"
          value={changes?.yoy.pct === null || changes?.yoy.pct === undefined
            ? "—"
            : `${changes.yoy.pct >= 0 ? "+" : ""}${changes.yoy.pct.toFixed(1)}%`}
          delta={changes === null ? undefined : { pct: null, unavailableReason: changes.yoy.unavailableReason }}
        />
      </section>

      <section className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <ChartPanel
            title="APIx headline vs. official CPI air-fare series"
            subtitle="Both series indexed to the same reference period."
            isLoading={headline.isLoading || cpi.isLoading}
            error={headline.error ?? cpi.error}
            isEmpty={option === null ? false : headline.data?.items.length === 0}
            dataStatus={headline.data?.meta.data_status}
            table={table}
          >
            {option !== null && (
              <EChart
                option={option}
                height={340}
                ariaLabel="Line chart comparing the APIx headline index to the official CPI transport air-fare series over time"
                nav={nav}
              />
            )}
          </ChartPanel>
        </div>

        <ChartPanel
          title="Route momentum"
          subtitle="Corridors coloured by change vs. the previous period."
          isLoading={routesWithCoords.isLoading || heatmap.isLoading}
          error={routesWithCoords.error ?? heatmap.error}
          isEmpty={corridors.length === 0}
          emptyDetail="No routes with known airport coordinates in the current basket."
          table={mapTable}
        >
          {corridors.length > 0 && <RouteMap corridors={corridors} compact />}
        </ChartPanel>
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartPanel
          title="Data freshness — today"
          subtitle="Per-source collection status."
          isLoading={coverage.isLoading}
          error={coverage.error}
          isEmpty={coverage.data?.sources.length === 0}
          dataStatus={coverage.data?.meta.data_status}
        >
          {coverage.data !== undefined && <CoverageStrip coverage={coverage.data} />}
        </ChartPanel>

        <ChartPanel
          title="Coverage"
          subtitle="Basket routes with data today."
          isLoading={coverage.isLoading}
          error={coverage.error}
          dataStatus={coverage.data?.meta.data_status}
        >
          {coverage.data !== undefined && <CoverageIndicator coverage={coverage.data} />}
        </ChartPanel>
      </section>

      <section aria-label="Recent activity and access" className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <ChartPanel
          title="Recent revisions"
          subtitle="Latest corrections to published values."
          isLoading={revisions.isLoading}
          error={revisions.error}
          isEmpty={revisions.data?.items.length === 0}
          emptyDetail="No revisions have been recorded yet."
          dataStatus={revisions.data?.meta.data_status}
        >
          {revisions.data !== undefined && (
            <ul className="flex flex-col gap-3">
              {revisions.data.items.slice(0, 4).map((r, i) => (
                <li key={i} className="flex gap-3 border-b border-grid pb-3 last:border-0 last:pb-0">
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-ink">
                    <IconHistory width={14} height={14} />
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm text-ink">
                      <span className="font-mono font-medium">{r.series}</span> ·{" "}
                      {formatPeriod(r.period)}:{" "}
                      {r.old_value === null || r.old_value === undefined ? (
                        <span className="font-mono">first published at {formatIndex(r.new_value)}</span>
                      ) : (
                        <span className="font-mono">
                          {formatIndex(r.old_value)} → {formatIndex(r.new_value)}
                        </span>
                      )}
                    </p>
                    <p className="mt-0.5 truncate text-xs text-ink-2">
                      {formatDate(r.revised_at.slice(0, 10))} — {r.reason}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </ChartPanel>

        <div className="rounded-2xl border border-edge bg-surface p-5 shadow-card">
          <div className="mb-3 flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-soft text-accent-ink">
              <IconDownload />
            </span>
            <div>
              <h2 className="text-base font-semibold text-ink">Data explorer</h2>
              <p className="text-sm text-ink-2">Download the headline series.</p>
            </div>
          </div>
          <p className="mb-4 text-sm text-ink-2">
            One row per period, with the index run and data status carried on every line — a
            downloaded file stays traceable once it leaves this dashboard.
          </p>
          <a
            href={csvUrl}
            className="inline-flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-semibold text-white transition-colors hover:brightness-110"
          >
            <IconDownload width={15} height={15} />
            Download CSV
          </a>
        </div>

        <div className="rounded-2xl border border-edge bg-surface p-5 shadow-card">
          <div className="mb-3 flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-soft text-accent-ink">
              <IconCode />
            </span>
            <div>
              <h2 className="text-base font-semibold text-ink">API access</h2>
              <p className="text-sm text-ink-2">Integrate APIx into your own systems.</p>
            </div>
          </div>
          <div className="mb-4 flex items-center gap-2 rounded-lg bg-raised px-3 py-2">
            <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap font-mono text-xs text-ink">
              {EXAMPLE_REQUEST}
            </code>
            <CopyButton text={EXAMPLE_REQUEST} />
          </div>
          <a
            href={`${BASE_URL}/docs`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-full border border-edge px-4 py-2 text-sm font-semibold text-ink-2 transition-colors hover:border-accent hover:text-accent-ink"
          >
            View API documentation
          </a>
        </div>
      </section>
    </div>
  );
}
