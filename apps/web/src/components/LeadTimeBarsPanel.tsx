/**
 * Dashboard-sized lead-time bars for one route: mean fare per advance-purchase window,
 * bar colour scaled by `index_vs_cheapest` (the same field the full /leadtime screen
 * reports) so darker really does mean "further from the cheapest window", not an
 * arbitrary palette.
 */

import { useMemo } from "react";
import { useLeadtime } from "../api/hooks";
import { formatINR } from "../lib/format";
import { useTheme } from "../theme/ThemeContext";
import { baseOption, gridDefaults, timeAxis, tooltipDefaults, valueAxis } from "../theme/echartsTheme";
import { ChartPanel } from "./ChartPanel";
import { EChart } from "./EChart";

export function LeadTimeBarsPanel({ routeCode, carrier }: { routeCode: string; carrier: string }) {
  const { tokens } = useTheme();
  const leadtime = useLeadtime(routeCode, carrier === "" ? undefined : carrier);

  const option = useMemo(() => {
    if (leadtime.data === undefined) return null;
    const buckets = leadtime.data.buckets;
    const maxIdx = Math.max(100, ...buckets.map((b) => b.index_vs_cheapest));
    const ramp = tokens.sequential;
    return {
      ...baseOption(tokens),
      grid: { ...gridDefaults(), left: 60, top: 14 },
      tooltip: {
        ...tooltipDefaults(tokens),
        trigger: "axis" as const,
        formatter: (params: Array<{ dataIndex: number }>) => {
          const b = buckets[params[0]?.dataIndex ?? 0];
          if (b === undefined) return "";
          return `${b.min_days}–${b.max_days}d before departure<br/>${formatINR(b.mean_fare)} (index ${b.index_vs_cheapest.toFixed(0)} vs. cheapest)`;
        },
      },
      xAxis: { ...timeAxis(tokens), data: buckets.map((b) => `${b.min_days}–${b.max_days}d`) },
      yAxis: valueAxis(tokens, undefined, { min: 0 }),
      series: [
        {
          type: "bar" as const,
          data: buckets.map((b) => ({
            value: b.mean_fare,
            itemStyle: {
              color: ramp[Math.round(((b.index_vs_cheapest - 100) / (maxIdx - 100 || 1)) * (ramp.length - 1))] ?? ramp[0],
              borderRadius: [4, 4, 0, 0] as [number, number, number, number],
            },
          })),
          barMaxWidth: 36,
        },
      ],
    };
  }, [leadtime.data, tokens]);

  const table = useMemo(() => {
    if (leadtime.data === undefined) return undefined;
    return {
      caption: `Lead-time bars for ${routeCode}${carrier === "" ? "" : ` (${carrier})`}`,
      columns: ["Window", "Mean fare", "Index vs. cheapest"],
      rows: leadtime.data.buckets.map((b) => [
        `${b.min_days}–${b.max_days}d`,
        formatINR(b.mean_fare),
        b.index_vs_cheapest.toFixed(0),
      ]),
    };
  }, [leadtime.data, routeCode, carrier]);

  return (
    <ChartPanel
      title="Lead-time analysis"
      subtitle={`${routeCode}${carrier === "" ? "" : ` — ${carrier}`}, mean fare by advance window`}
      isLoading={leadtime.isLoading}
      error={leadtime.error}
      isEmpty={leadtime.data?.buckets.length === 0}
      table={table}
    >
      {option !== null && (
        <EChart option={option} height={200} ariaLabel={`Mean fare by advance-purchase window for ${routeCode}`} />
      )}
    </ChartPanel>
  );
}
