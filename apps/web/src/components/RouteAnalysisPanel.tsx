/**
 * Dashboard-sized fare curve for one route — the cheapest advance window, unsplit. The
 * full split-by-window/carrier view with its own map lives at /routes; this is a preview
 * that links there, not a duplicate of it.
 */

import { useMemo } from "react";
import { useBasket, useRouteSeries } from "../api/hooks";
import { formatINR, formatPeriod } from "../lib/format";
import { useTheme } from "../theme/ThemeContext";
import { baseOption, gridDefaults, timeAxis, tooltipDefaults, valueAxis } from "../theme/echartsTheme";
import { ChartPanel } from "./ChartPanel";
import { EChart } from "./EChart";

export function RouteAnalysisPanel({ routeCode }: { routeCode: string }) {
  const { tokens } = useTheme();
  const basket = useBasket();
  const cheapestWindow = basket.data?.advance_windows[0];
  const series = useRouteSeries(routeCode, cheapestWindow?.min_days);

  const option = useMemo(() => {
    if (series.data === undefined) return null;
    const items = series.data.items;
    const periods = items.map((p) => formatPeriod(p.period));
    const soldOut = new Set(items.flatMap((p, i) => (p.sold_out ? [i] : [])));
    return {
      ...baseOption(tokens),
      grid: { ...gridDefaults(), left: 60, top: 14 },
      tooltip: {
        ...tooltipDefaults(tokens),
        formatter: (params: Array<{ dataIndex: number }>) => {
          const p = items[params[0]?.dataIndex ?? 0];
          if (p === undefined) return "";
          return `${formatPeriod(p.period)}<br/>${formatINR(p.mean_fare)}${p.sold_out ? " (sold out)" : ""}`;
        },
      },
      xAxis: { ...timeAxis(tokens), data: periods },
      yAxis: valueAxis(tokens),
      series: [
        {
          type: "line" as const,
          data: items.map((p) => p.mean_fare),
          lineStyle: { width: 2, color: tokens.series[0] },
          itemStyle: { color: tokens.series[0] },
          showSymbol: false,
          markArea:
            soldOut.size === 0
              ? undefined
              : {
                  itemStyle: { color: tokens.inkMuted, opacity: 0.12 },
                  data: [...soldOut].map((idx) => [{ xAxis: idx - 0.5 }, { xAxis: idx + 0.5 }]),
                },
        },
      ],
    };
  }, [series.data, tokens]);

  const table = useMemo(() => {
    if (series.data === undefined) return undefined;
    return {
      caption: `Fare curve for ${routeCode}, ${cheapestWindow?.label ?? "cheapest window"}`,
      columns: ["Period", "Mean fare", "Quotes"],
      rows: series.data.items.map((p) => [
        formatPeriod(p.period),
        `${formatINR(p.mean_fare)}${p.sold_out ? " (sold out)" : ""}`,
        p.n_quotes.toLocaleString("en-IN"),
      ]),
    };
  }, [series.data, routeCode, cheapestWindow]);

  return (
    <ChartPanel
      title="Route analysis"
      subtitle={`${routeCode} — ${cheapestWindow?.label ?? "cheapest window"}`}
      isLoading={basket.isLoading || series.isLoading}
      error={basket.error ?? series.error}
      isEmpty={series.data?.items.length === 0}
      table={table}
    >
      {option !== null && (
        <EChart
          option={option}
          height={200}
          ariaLabel={`Mean fare over time for ${routeCode}`}
        />
      )}
    </ChartPanel>
  );
}
