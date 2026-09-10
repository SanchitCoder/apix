/**
 * Screen 3 — Sector heatmap.
 *
 * Routes x dates, coloured by deviation from each route's own baseline (its mean over
 * the returned window). Diverging scale centred on zero, so a route's own volatility is
 * visible independent of its price level relative to other routes.
 */

import { useMemo } from "react";
import { useHeatmap } from "../api/hooks";
import { ChartPanel } from "../components/ChartPanel";
import { EChart } from "../components/EChart";
import { HeatmapArt } from "../components/illustrations";
import { PageHeader } from "../components/PageHeader";
import { formatPeriod } from "../lib/format";
import { useTheme } from "../theme/ThemeContext";
import { baseOption, chartText, divergingRamp, gridDefaults, tooltipDefaults } from "../theme/echartsTheme";

export default function SectorHeatmap() {
  const { tokens } = useTheme();
  const heatmap = useHeatmap();

  const derived = useMemo(() => {
    if (heatmap.data === undefined) return null;
    const routes = [...new Set(heatmap.data.items.map((c) => c.route_code))];
    const periods = [...new Set(heatmap.data.items.map((c) => c.period))].sort();
    const baselineByRoute = new Map<string, number>();
    for (const route of routes) {
      const values = heatmap.data.items.filter((c) => c.route_code === route).map((c) => c.value);
      baselineByRoute.set(route, values.reduce((a, b) => a + b, 0) / values.length);
    }
    const cells = heatmap.data.items.map((c) => {
      const baseline = baselineByRoute.get(c.route_code) ?? c.value;
      return {
        route: c.route_code,
        period: c.period,
        deviationPct: ((c.value - baseline) / baseline) * 100,
        value: c.value,
        n_quotes: c.n_quotes,
      };
    });
    const maxAbsDeviation = Math.max(1, ...cells.map((c) => Math.abs(c.deviationPct)));
    return { routes, periods, cells, maxAbsDeviation };
  }, [heatmap.data]);

  const option = useMemo(() => {
    if (derived === null) return null;
    const { routes, periods, cells, maxAbsDeviation } = derived;
    const points = cells.map((c) => [
      periods.indexOf(c.period),
      routes.indexOf(c.route),
      Math.round(c.deviationPct * 10) / 10,
    ]);
    return {
      ...baseOption(tokens),
      grid: { ...gridDefaults(), left: 100 },
      tooltip: {
        ...tooltipDefaults(tokens),
        trigger: "item" as const,
        formatter: (params: { data: [number, number, number] }) => {
          const [pIdx, rIdx, dev] = params.data;
          return `${routes[rIdx]}, ${formatPeriod(periods[pIdx] ?? "")}<br/>Deviation from baseline: ${dev >= 0 ? "+" : ""}${dev}%`;
        },
      },
      xAxis: {
        type: "category" as const,
        data: periods.map(formatPeriod),
        axisLine: { lineStyle: { color: tokens.axis } },
        axisTick: { show: false },
        axisLabel: chartText(tokens),
        splitArea: { show: true },
      },
      yAxis: {
        type: "category" as const,
        data: routes,
        axisLine: { lineStyle: { color: tokens.axis } },
        axisTick: { show: false },
        axisLabel: chartText(tokens),
        splitArea: { show: true },
      },
      visualMap: {
        type: "continuous" as const,
        min: -maxAbsDeviation,
        max: maxAbsDeviation,
        calculable: true,
        orient: "horizontal" as const,
        left: "center",
        bottom: 0,
        text: ["Above baseline", "Below baseline"],
        textStyle: chartText(tokens),
        inRange: { color: divergingRamp(tokens) },
      },
      series: [
        {
          type: "heatmap" as const,
          data: points,
          itemStyle: { borderColor: tokens.surface, borderWidth: 2 },
          emphasis: { itemStyle: { borderColor: tokens.inkPrimary, borderWidth: 1 } },
        },
      ],
    };
  }, [derived, tokens]);

  const nav = useMemo(() => {
    if (derived === null) return undefined;
    return {
      seriesCount: 1,
      pointCount: () => derived.cells.length,
      describe: (_s: number, d: number) => {
        const c = derived.cells[d];
        if (c === undefined) return "";
        return `${c.route}, ${formatPeriod(c.period)}: ${c.deviationPct >= 0 ? "+" : ""}${c.deviationPct.toFixed(1)}% from baseline.`;
      },
    };
  }, [derived]);

  const table = useMemo(() => {
    if (derived === null) return undefined;
    return {
      caption: "Route deviation from its own baseline, by period",
      columns: ["Route", "Period", "Index value", "Deviation from baseline", "Quotes"],
      rows: derived.cells.map((c) => [
        c.route,
        formatPeriod(c.period),
        c.value.toFixed(1),
        `${c.deviationPct >= 0 ? "+" : ""}${c.deviationPct.toFixed(1)}%`,
        c.n_quotes.toLocaleString("en-IN"),
      ]),
    };
  }, [derived]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Sector heatmap"
        subtitle="Routes by period, coloured by deviation from each route's own baseline — its own volatility, independent of its price level relative to other routes."
        art={<HeatmapArt />}
      />

      <ChartPanel
        title="Sector heatmap"
        subtitle="Each route's colour is relative to its own baseline, not to other routes."
        isLoading={heatmap.isLoading}
        error={heatmap.error}
        isEmpty={derived?.cells.length === 0}
        dataStatus={heatmap.data?.meta.data_status}
        table={table}
      >
        {option !== null && (
          <EChart
            option={option}
            height={420}
            ariaLabel="Heatmap of routes by period, coloured by deviation from each route's own baseline fare"
            nav={nav}
          />
        )}
      </ChartPanel>
    </div>
  );
}
