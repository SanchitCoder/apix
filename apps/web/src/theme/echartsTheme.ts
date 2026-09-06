/**
 * ECharts option fragments derived from the theme tokens.
 *
 * Screens compose these instead of writing colour or type literals: recessive hairline
 * grid, muted axis ink, themed tooltip, thin marks. Anything colour-like in a chart
 * option must trace back to `ThemeTokens`.
 */

import type {
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
  XAXisComponentOption,
  YAXisComponentOption,
} from "echarts";
import type { ThemeTokens } from "./tokens";

export function chartText(t: ThemeTokens) {
  return { fontFamily: t.fontFamily, fontSize: t.fontSize.sm, color: t.inkSecondary };
}

export function gridDefaults(): GridComponentOption {
  // Room for axis labels on every side; the container must include the x-axis band.
  // left:84 has room for the rotated y-axis name running down the left edge (see
  // valueAxis) without crowding the tick numbers; top:44 is just the legend row.
  return { left: 84, right: 20, top: 44, bottom: 40, containLabel: false };
}

export function tooltipDefaults(t: ThemeTokens): TooltipComponentOption {
  return {
    trigger: "axis",
    axisPointer: { type: "line", lineStyle: { color: t.axis } },
    backgroundColor: t.surfaceRaised,
    borderColor: t.border,
    borderWidth: 1,
    textStyle: { color: t.inkPrimary, fontFamily: t.fontFamily, fontSize: t.fontSize.sm },
  };
}

export function legendDefaults(t: ThemeTokens): LegendComponentOption {
  // `scroll` pins the legend to a single row (paged with arrows) regardless of how many
  // series a screen throws at it — a wrapped multi-row legend grows downward by an
  // amount gridDefaults()/valueAxis() can't predict, and collides with the y-axis name
  // sitting just below it.
  return {
    type: "scroll",
    top: 20,
    left: 0,
    right: 32,
    icon: "circle",
    itemWidth: 10,
    itemHeight: 10,
    textStyle: chartText(t),
    pageIconColor: t.inkSecondary,
    pageIconInactiveColor: t.axis,
    pageTextStyle: chartText(t),
  };
}

export function timeAxis(t: ThemeTokens): XAXisComponentOption {
  return {
    type: "category",
    axisLine: { lineStyle: { color: t.axis } },
    axisTick: { show: false },
    axisLabel: { ...chartText(t), color: t.inkMuted },
    splitLine: { show: false },
  };
}

export function valueAxis(t: ThemeTokens, name?: string, opts?: { min?: number }): YAXisComponentOption {
  return {
    type: "value",
    ...(opts?.min !== undefined ? { min: opts.min } : {}),
    // The unit name runs vertically down the left edge (nameLocation "middle" + a
    // 90-degree rotation) rather than floating above the plot — the legend already
    // lives up there, in a row whose height varies with series count, so anything
    // pinned by a fixed offset above the grid drifts into it.
    ...(name !== undefined
      ? {
          name,
          nameLocation: "middle" as const,
          nameGap: 58,
          nameRotate: 90,
          nameTextStyle: { ...chartText(t), color: t.inkMuted },
        }
      : {}),
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { ...chartText(t), color: t.inkMuted },
    splitLine: { lineStyle: { color: t.grid, type: "solid" as const } },
    scale: true,
  };
}

/** Shared root-level defaults: categorical order, ink, transparent canvas over the panel. */
export function baseOption(t: ThemeTokens) {
  return {
    color: [...t.series],
    backgroundColor: "transparent",
    textStyle: { fontFamily: t.fontFamily, fontSize: t.fontSize.sm, color: t.inkSecondary },
    animationDuration: 200,
  };
}

/** Diverging ramp for a scale centred on zero: cool pole → neutral → warm pole. */
export function divergingRamp(t: ThemeTokens): string[] {
  return [...t.divergingNeg, t.divergingMid, ...t.divergingPos];
}
