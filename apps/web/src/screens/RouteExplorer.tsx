/**
 * Screen 2 — Route explorer.
 *
 * Route selector; fare curve over time split by advance window or by carrier; sold-out
 * days shaded; a map view of corridors coloured by momentum.
 *
 * The corridor map is limited to the three airports (DEL, BOM, BLR) whose coordinates
 * exist in db/seeds/airports.csv as served today — extending it to the full basket is a
 * Phase 2 change to the coordinate lookup, not something to approximate here.
 */

import { useMemo, useState } from "react";
import { useBasket, useCarriers, useRouteSeriesBatch, useRoutes, useHeatmap } from "../api/hooks";
import { ChartPanel } from "../components/ChartPanel";
import { EChart } from "../components/EChart";
import { RouteExplorerArt } from "../components/illustrations";
import { PageHeader } from "../components/PageHeader";
import { RouteMap } from "../components/RouteMap";
import { buildCorridors } from "../lib/corridors";
import { formatINR, formatPeriod } from "../lib/format";
import { useTheme } from "../theme/ThemeContext";
import {
  baseOption,
  gridDefaults,
  legendDefaults,
  timeAxis,
  tooltipDefaults,
  valueAxis,
} from "../theme/echartsTheme";

type SplitMode = "window" | "carrier";

export default function RouteExplorer() {
  const { tokens } = useTheme();
  const basket = useBasket();
  const carriers = useCarriers();
  const routesWithCoords = useRoutes();
  const heatmap = useHeatmap();

  const [routeCode, setRouteCode] = useState("DEL-BOM");
  const [split, setSplit] = useState<SplitMode>("window");

  const windowVariants = useMemo(
    () =>
      (basket.data?.advance_windows ?? []).map((w) => ({
        key: w.code,
        label: w.label,
        // The series endpoint restricts to one exact lead time (it isn't a range query),
        // so a window is represented by its midpoint day rather than its lower bound —
        // collected quotes cluster near the middle of a window, not its edge.
        advanceDays: Math.floor((w.min_days + w.max_days) / 2),
      })),
    [basket.data],
  );
  const carrierVariants = useMemo(
    () =>
      (carriers.data?.carriers ?? []).map((c) => ({
        key: c.iata,
        label: `${c.name} (${c.iata})`,
        carrier: c.iata,
      })),
    [carriers.data],
  );

  const activeVariants = split === "window" ? windowVariants : carrierVariants;
  const batch = useRouteSeriesBatch(
    routeCode,
    activeVariants.map((v) => ({
      key: v.key,
      advanceDays: "advanceDays" in v ? v.advanceDays : undefined,
      carrier: "carrier" in v ? v.carrier : undefined,
    })),
  );

  const isLoading = batch.some((q) => q.isLoading) || (split === "window" ? basket.isLoading : carriers.isLoading);
  const firstError = batch.find((q) => q.error)?.error;
  const allLoaded = batch.every((q) => q.data !== undefined) && activeVariants.length > 0;

  const option = useMemo(() => {
    if (!allLoaded) return null;
    const periods = batch[0]?.data?.items.map((p) => formatPeriod(p.period)) ?? [];
    const soldOutIndices = new Set<number>();
    batch.forEach((q) => {
      q.data?.items.forEach((p, i) => {
        if (p.sold_out) soldOutIndices.add(i);
      });
    });
    return {
      ...baseOption(tokens),
      grid: gridDefaults(),
      tooltip: tooltipDefaults(tokens),
      legend: legendDefaults(tokens),
      xAxis: { ...timeAxis(tokens), data: periods },
      yAxis: valueAxis(tokens, "Mean fare (INR)"),
      series: activeVariants.map((v, i) => ({
        name: v.label,
        type: "line" as const,
        data: batch[i]?.data?.items.map((p) => p.mean_fare) ?? [],
        lineStyle: { width: 2 },
        showSymbol: false,
        ...(i === 0
          ? {
              markArea: {
                itemStyle: { color: tokens.inkMuted, opacity: 0.12 },
                data: [...soldOutIndices].map((idx) => [
                  { xAxis: idx - 0.5 },
                  { xAxis: idx + 0.5 },
                ]),
              },
            }
          : {}),
      })),
    };
  }, [allLoaded, batch, activeVariants, tokens]);

  const nav = useMemo(() => {
    if (!allLoaded) return undefined;
    const periods = batch[0]?.data?.items.map((p) => p.period) ?? [];
    return {
      seriesCount: activeVariants.length,
      pointCount: () => periods.length,
      describe: (s: number, d: number) => {
        const variant = activeVariants[s];
        const point = batch[s]?.data?.items[d];
        if (variant === undefined || point === undefined) return "";
        return `${variant.label}, ${formatPeriod(point.period)}: ${formatINR(point.mean_fare)}${
          point.sold_out ? ", sold out" : ""
        }.`;
      },
    };
  }, [allLoaded, batch, activeVariants]);

  const table = useMemo(() => {
    if (!allLoaded) return undefined;
    const periods = batch[0]?.data?.items.map((p) => p.period) ?? [];
    return {
      caption: `Fare curve for ${routeCode}, split by ${split === "window" ? "advance window" : "carrier"}`,
      columns: ["Period", ...activeVariants.map((v) => v.label)],
      rows: periods.map((period, i) => [
        formatPeriod(period),
        ...activeVariants.map((_, vi) => {
          const point = batch[vi]?.data?.items[i];
          if (point === undefined) return "—";
          return `${formatINR(point.mean_fare)}${point.sold_out ? " (sold out)" : ""}`;
        }),
      ]),
    };
  }, [allLoaded, batch, activeVariants, routeCode, split]);

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

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Route explorer"
        subtitle="Fare curves for one route at a time, split by advance-purchase window or by carrier, with sold-out days shaded and corridors coloured by momentum."
        art={<RouteExplorerArt />}
      />

      <div className="flex flex-wrap items-end gap-4 rounded-2xl border border-edge bg-surface p-5 shadow-card">
        <div>
          <label htmlFor="route-select" className="block text-sm font-medium text-ink-2">
            Route
          </label>
          <select
            id="route-select"
            value={routeCode}
            onChange={(e) => setRouteCode(e.target.value)}
            className="mt-1.5 rounded-lg border border-edge bg-raised px-3 py-2 text-sm text-ink transition-colors focus:border-accent"
          >
            {(basket.data?.routes ?? []).map((r) => (
              <option key={r.code} value={r.code}>
                {r.code}
              </option>
            ))}
          </select>
        </div>
        <fieldset>
          <legend className="block text-sm font-medium text-ink-2">Split fare curve by</legend>
          <div
            className="mt-1.5 inline-flex gap-1 rounded-full border border-edge bg-raised p-1"
            role="radiogroup"
            aria-label="Split fare curve by"
          >
            {(["window", "carrier"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={split === mode}
                onClick={() => setSplit(mode)}
                className={`rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
                  split === mode
                    ? "bg-accent text-navy shadow-sm"
                    : "text-ink-2 hover:text-ink"
                }`}
              >
                {mode === "window" ? "Advance window" : "Carrier"}
              </button>
            ))}
          </div>
        </fieldset>
      </div>

      <ChartPanel
        title={`Fare curve — ${routeCode}`}
        subtitle="Shaded bands mark periods where the cheapest window was fully sold out."
        isLoading={isLoading}
        error={firstError}
        isEmpty={allLoaded && activeVariants.length === 0}
        table={table}
      >
        {option !== null && (
          <EChart
            option={option}
            height={360}
            ariaLabel={`Fare curve for ${routeCode}, split by ${split === "window" ? "advance window" : "carrier"}`}
            nav={nav}
          />
        )}
      </ChartPanel>

      <ChartPanel
        title="Corridor momentum"
        subtitle="Airports with known coordinates only. Colour is the diverging scale, centred on zero."
        isLoading={routesWithCoords.isLoading || heatmap.isLoading}
        error={routesWithCoords.error ?? heatmap.error}
        isEmpty={corridors.length === 0}
        table={mapTable}
      >
        {corridors.length > 0 && <RouteMap corridors={corridors} />}
      </ChartPanel>
    </div>
  );
}
