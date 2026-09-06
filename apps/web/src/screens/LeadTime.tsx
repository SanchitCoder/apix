/**
 * Screen 4 — Lead-time curve.
 *
 * Price against days-to-departure per route and carrier, with the inflection point
 * marked (the window past which price stops falling as departure gets further away),
 * and confidence bands from the underlying quartile dispersion.
 */

import { useMemo, useState } from "react";
import { useBasket, useCarriers, useLeadtime } from "../api/hooks";
import { ChartPanel } from "../components/ChartPanel";
import { EChart } from "../components/EChart";
import { formatINR } from "../lib/format";
import { useTheme } from "../theme/ThemeContext";
import {
  baseOption,
  gridDefaults,
  legendDefaults,
  timeAxis,
  tooltipDefaults,
  valueAxis,
} from "../theme/echartsTheme";

export default function LeadTime() {
  const { tokens } = useTheme();
  const basket = useBasket();
  const carriers = useCarriers();

  const [routeCode, setRouteCode] = useState("DEL-BOM");
  const [carrier, setCarrier] = useState<string>("");

  const leadtime = useLeadtime(routeCode, carrier === "" ? undefined : carrier);

  const inflection = useMemo(() => {
    if (leadtime.data === undefined) return null;
    // The window furthest from departure, at or after which price stops falling: the
    // minimum of the mean-fare curve read from the longest lead time inward.
    let best = leadtime.data.buckets[0];
    for (const bucket of leadtime.data.buckets) {
      if (best === undefined || bucket.mean_fare <= best.mean_fare) best = bucket;
    }
    return best ?? null;
  }, [leadtime.data]);

  const option = useMemo(() => {
    if (leadtime.data === undefined) return null;
    const buckets = leadtime.data.buckets;
    const labels = buckets.map((b) => `${b.min_days}–${b.max_days}d`);
    return {
      ...baseOption(tokens),
      grid: gridDefaults(),
      tooltip: {
        ...tooltipDefaults(tokens),
        trigger: "axis" as const,
        formatter: (params: Array<{ dataIndex: number }>) => {
          const b = buckets[params[0]?.dataIndex ?? 0];
          if (b === undefined) return "";
          return [
            `<strong>${b.min_days}–${b.max_days} days before departure</strong>`,
            `Mean: ${formatINR(b.mean_fare)}`,
            `Median: ${formatINR(b.median_fare)}`,
            `IQR: ${formatINR(b.p25_fare)} – ${formatINR(b.p75_fare)}`,
            `vs. cheapest window: ${b.index_vs_cheapest.toFixed(0)}`,
          ].join("<br/>");
        },
      },
      legend: legendDefaults(tokens),
      xAxis: {
        ...timeAxis(tokens),
        data: labels,
        name: "Days before departure",
        nameLocation: "middle" as const,
        nameGap: 32,
        nameTextStyle: { color: tokens.inkMuted, fontFamily: tokens.fontFamily, fontSize: tokens.fontSize.sm },
      },
      // min:0 — the interquartile band below is drawn as a stacked pair of series (an
      // invisible p75 area plus a negative-valued "gap" area beneath it) purely as an
      // ECharts stacking trick; scale:true would otherwise auto-extend the axis down to
      // include that internal negative value, even though no fare is ever negative.
      yAxis: valueAxis(tokens, "Fare (INR)", { min: 0 }),
      // "Mean fare" is series index 0 deliberately: EChart's keyboard layer dispatches
      // highlight/tooltip actions by series index, and only this series should receive
      // them — the two band series below are `silent` visual fill, not walkable data.
      series: [
        {
          name: "Mean fare",
          type: "line" as const,
          data: buckets.map((b) => b.mean_fare),
          lineStyle: { width: 2, color: tokens.series[0] },
          itemStyle: { color: tokens.series[0] },
          showSymbol: false,
          z: 2,
          markPoint:
            inflection === null
              ? undefined
              : {
                  symbol: "circle",
                  symbolSize: 10,
                  itemStyle: { color: tokens.status.warning, borderColor: tokens.surface, borderWidth: 2 },
                  label: { show: false },
                  data: [
                    {
                      name: "Inflection point",
                      xAxis: buckets.findIndex((b) => b.window_code === inflection.window_code),
                      yAxis: inflection.mean_fare,
                    },
                  ],
                },
        },
        {
          name: "Interquartile band",
          type: "line" as const,
          data: buckets.map((b) => b.p75_fare),
          lineStyle: { opacity: 0 },
          areaStyle: { color: tokens.series[0], opacity: 0.12 },
          stack: "band",
          symbol: "none" as const,
          silent: true,
          z: 1,
          tooltip: { show: false },
          legendHoverLink: false,
        },
        {
          name: "Interquartile band (lower)",
          type: "line" as const,
          data: buckets.map((b, i) => b.p25_fare - (buckets[i]?.p75_fare ?? 0)),
          lineStyle: { opacity: 0 },
          areaStyle: { color: tokens.surface, opacity: 1 },
          stack: "band",
          symbol: "none" as const,
          silent: true,
          z: 1,
          tooltip: { show: false },
          legendHoverLink: false,
        },
      ],
    };
  }, [leadtime.data, inflection, tokens]);

  const nav = useMemo(() => {
    if (leadtime.data === undefined) return undefined;
    const buckets = leadtime.data.buckets;
    return {
      seriesCount: 1,
      pointCount: () => buckets.length,
      describe: (_s: number, d: number) => {
        const b = buckets[d];
        if (b === undefined) return "";
        return `${b.min_days} to ${b.max_days} days before departure: mean ${formatINR(
          b.mean_fare,
        )}, interquartile range ${formatINR(b.p25_fare)} to ${formatINR(b.p75_fare)}.`;
      },
    };
  }, [leadtime.data]);

  const table = useMemo(() => {
    if (leadtime.data === undefined) return undefined;
    return {
      caption: `Lead-time fare curve for ${routeCode}${carrier === "" ? "" : ` (${carrier})`}`,
      columns: ["Window", "Mean", "Median", "P25", "P75", "vs. cheapest", "Quotes"],
      rows: leadtime.data.buckets.map((b) => [
        `${b.min_days}–${b.max_days}d`,
        formatINR(b.mean_fare),
        formatINR(b.median_fare),
        formatINR(b.p25_fare),
        formatINR(b.p75_fare),
        b.index_vs_cheapest.toFixed(0),
        b.n_quotes.toLocaleString("en-IN"),
      ]),
    };
  }, [leadtime.data, routeCode, carrier]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end gap-4 rounded-2xl border border-edge bg-surface p-5 shadow-card">
        <div>
          <label htmlFor="lt-route" className="block text-sm font-medium text-ink-2">
            Route
          </label>
          <select
            id="lt-route"
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
        <div>
          <label htmlFor="lt-carrier" className="block text-sm font-medium text-ink-2">
            Carrier
          </label>
          <select
            id="lt-carrier"
            value={carrier}
            onChange={(e) => setCarrier(e.target.value)}
            className="mt-1.5 rounded-lg border border-edge bg-raised px-3 py-2 text-sm text-ink transition-colors focus:border-accent"
          >
            <option value="">All carriers</option>
            {(carriers.data?.carriers ?? []).map((c) => (
              <option key={c.iata} value={c.iata}>
                {c.name} ({c.iata})
              </option>
            ))}
          </select>
        </div>
      </div>

      <ChartPanel
        title={`Lead-time curve — ${routeCode}`}
        subtitle="Shaded band is the interquartile range; the marked point is the inflection where price stops falling further from departure."
        isLoading={leadtime.isLoading}
        error={leadtime.error}
        isEmpty={leadtime.data?.buckets.length === 0}
        dataStatus={leadtime.data?.meta.data_status}
        table={table}
      >
        {option !== null && (
          <EChart
            option={option}
            height={380}
            ariaLabel={`Lead-time fare curve for ${routeCode}, mean fare with interquartile band by advance-purchase window`}
            nav={nav}
          />
        )}
      </ChartPanel>
    </div>
  );
}
