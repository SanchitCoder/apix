/**
 * The dashboard's anchor visual: the headline index over time, with a trailing
 * moving average and the method's own base-period reference line — both real,
 * derived-or-configured values, never a fabricated regulatory "ceiling." A second,
 * synced panel underneath plots `n_quotes` per period as bars, the same real
 * evidence-count ChartPanel already surfaces elsewhere, here read as a volume strip.
 */

import { useMemo } from "react";
import type { IndexPoint } from "../api/client";
import { formatIndex, formatPeriod } from "../lib/format";
import { useTheme } from "../theme/ThemeContext";
import { baseOption, gridDefaults, timeAxis, tooltipDefaults, valueAxis } from "../theme/echartsTheme";
import { EChart } from "./EChart";

function movingAverage(values: number[], window: number): (number | null)[] {
  return values.map((_, i) => {
    if (i < window - 1) return null;
    const slice = values.slice(i - window + 1, i + 1);
    return slice.reduce((a, b) => a + b, 0) / slice.length;
  });
}

interface IndexChartProps {
  items: IndexPoint[];
  referenceValue: number;
}

export function IndexChart({ items, referenceValue }: IndexChartProps) {
  const { tokens } = useTheme();

  const option = useMemo(() => {
    const periods = items.map((p) => formatPeriod(p.period));
    const values = items.map((p) => p.value);
    const quotes = items.map((p) => p.n_quotes);
    const sma = movingAverage(values, Math.min(3, values.length));

    return {
      ...baseOption(tokens),
      grid: [
        { ...gridDefaults(), top: 44, bottom: 108 },
        { left: 84, right: 20, top: "78%", height: "16%" },
      ],
      xAxis: [
        { ...timeAxis(tokens), data: periods, gridIndex: 0 },
        { ...timeAxis(tokens), data: periods, gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        { ...valueAxis(tokens, "Index (base = 100)"), gridIndex: 0 },
        {
          ...valueAxis(tokens),
          gridIndex: 1,
          name: "Quotes",
          nameGap: 40,
          splitLine: { show: false },
          splitNumber: 2,
          axisLabel: { ...valueAxis(tokens).axisLabel, showMaxLabel: true },
        },
      ],
      axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
      tooltip: { ...tooltipDefaults(tokens), trigger: "axis" as const },
      legend: {
        top: 4,
        left: 0,
        icon: "roundRect" as const,
        itemWidth: 10,
        itemHeight: 3,
        textStyle: { color: tokens.inkSecondary, fontFamily: tokens.fontFamily, fontSize: tokens.fontSize.xs },
      },
      series: [
        {
          name: "Index",
          type: "line" as const,
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: values,
          showSymbol: values.length < 30,
          symbolSize: 5,
          lineStyle: { width: 2, color: tokens.accent },
          itemStyle: { color: tokens.accent },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: `${tokens.accent}33` },
                { offset: 1, color: `${tokens.accent}00` },
              ],
            },
          },
          markLine: {
            symbol: "none",
            silent: true,
            lineStyle: { color: tokens.inkMuted, type: "dashed" as const, width: 1 },
            label: {
              formatter: `Base period ({@value})`,
              position: "insideEndTop" as const,
              color: tokens.inkMuted,
              fontFamily: tokens.fontFamilyMono,
              fontSize: tokens.fontSize.xs,
            },
            data: [{ yAxis: referenceValue }],
          },
        },
        {
          name: "3-period moving average",
          type: "line" as const,
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: sma,
          showSymbol: false,
          connectNulls: false,
          lineStyle: { width: 1.5, type: "dotted" as const, color: tokens.series[2] },
        },
        {
          name: "Fare observations",
          type: "bar" as const,
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: quotes,
          itemStyle: { color: tokens.axis },
          barMaxWidth: 18,
        },
      ],
    };
  }, [items, referenceValue, tokens]);

  const nav = useMemo(
    () => ({
      seriesCount: 1,
      pointCount: () => items.length,
      describe: (_s: number, d: number) => {
        const point = items[d];
        return point === undefined
          ? ""
          : `${formatPeriod(point.period)}: index ${formatIndex(point.value)}, from ${point.n_quotes} quotes.`;
      },
    }),
    [items],
  );

  return (
    <EChart
      option={option}
      height={360}
      ariaLabel="India Airfare Price Index over time, with a 3-period moving average, the method's base-period reference line, and fare observation counts per period"
      nav={nav}
    />
  );
}
