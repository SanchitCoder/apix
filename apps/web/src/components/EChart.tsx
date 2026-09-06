/**
 * ECharts wrapper: mount/resize/dispose, plus the keyboard layer every chart gets.
 *
 * A chart is focusable; Left/Right walk the points of the active series, Up/Down switch
 * series, Home/End jump, Enter/Space activates a point (used by drill-downs). The
 * focused point drives the same tooltip a pointer user sees and is announced through an
 * aria-live region, so keyboard and screen-reader users read the same values. The data
 * table twin lives in ChartPanel; the tooltip is never the only way to a value.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart, LinesChart, ScatterChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";

/**
 * Screens build option objects against ECharts' full option surface, which the
 * upstream types model as a large, hard-to-satisfy discriminated union (series `type`
 * literals widen under normal object construction, mark-area tuples don't infer as
 * tuples, formatter callback params vary by trigger). Rather than fight that at every
 * call site, screens author a `ChartOption` (structurally close to `EChartsOption`) and
 * this wrapper is the one place that hands it to ECharts' imperative `setOption`.
 */
export type ChartOption = Record<string, unknown>;

echarts.use([
  LineChart,
  BarChart,
  HeatmapChart,
  ScatterChart,
  LinesChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  CanvasRenderer,
]);

export interface ChartNav {
  seriesCount: number;
  pointCount: (seriesIndex: number) => number;
  /** Sentence announced when a point receives keyboard focus. */
  describe: (seriesIndex: number, dataIndex: number) => string;
  onActivate?: (seriesIndex: number, dataIndex: number) => void;
}

interface EChartProps {
  option: ChartOption;
  height: number;
  /** One-sentence description of what the chart shows, for the accessible name. */
  ariaLabel: string;
  nav?: ChartNav;
  onPointClick?: (seriesIndex: number, dataIndex: number, value: unknown) => void;
  testId?: string;
}

export function EChart({ option, height, ariaLabel, nav, onPointClick, testId }: EChartProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const cursorRef = useRef<{ s: number; d: number }>({ s: 0, d: 0 });
  const [announcement, setAnnouncement] = useState("");
  const navRef = useRef<ChartNav | undefined>(nav);
  navRef.current = nav;

  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    const chart = echarts.init(host);
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(host);

    // Canvas text (axis labels, legend, tooltip) is measured against whatever font is
    // loaded at draw time. The UI font loads over the network with font-display: swap,
    // so a chart drawn before it lands measures with the fallback and never re-lays-out
    // when the real face swaps in wider — labels then overlap. Re-set once the browser
    // reports the face ready; a no-op if it already was.
    document.fonts?.ready
      .then(() => chart.setOption(chart.getOption(), { notMerge: true }))
      .catch(() => {
        /* font loading state unavailable — draw stands as-is */
      });

    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option as EChartsOption, { notMerge: true });
  }, [option]);

  useEffect(() => {
    const chart = chartRef.current;
    if (chart === null || onPointClick === undefined) return;
    const handler = (params: { seriesIndex?: number; dataIndex?: number; value?: unknown }) => {
      onPointClick(params.seriesIndex ?? 0, params.dataIndex ?? 0, params.value);
    };
    chart.on("click", handler);
    return () => {
      chart.off("click", handler);
    };
  }, [onPointClick]);

  const keyHandlers = useMemo(() => {
    const focusPoint = (s: number, d: number) => {
      const chart = chartRef.current;
      const currentNav = navRef.current;
      if (chart === null || currentNav === undefined) return;
      const seriesCount = currentNav.seriesCount;
      if (seriesCount === 0) return;
      const boundedS = Math.min(Math.max(s, 0), seriesCount - 1);
      const points = currentNav.pointCount(boundedS);
      if (points === 0) return;
      const boundedD = Math.min(Math.max(d, 0), points - 1);
      cursorRef.current = { s: boundedS, d: boundedD };
      chart.dispatchAction({ type: "downplay" });
      chart.dispatchAction({ type: "highlight", seriesIndex: boundedS, dataIndex: boundedD });
      chart.dispatchAction({ type: "showTip", seriesIndex: boundedS, dataIndex: boundedD });
      setAnnouncement(currentNav.describe(boundedS, boundedD));
    };

    const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
      const currentNav = navRef.current;
      if (currentNav === undefined) return;
      const { s, d } = cursorRef.current;
      switch (event.key) {
        case "ArrowRight":
          focusPoint(s, d + 1);
          break;
        case "ArrowLeft":
          focusPoint(s, d - 1);
          break;
        case "ArrowUp":
          focusPoint(s - 1, d);
          break;
        case "ArrowDown":
          focusPoint(s + 1, d);
          break;
        case "Home":
          focusPoint(s, 0);
          break;
        case "End":
          focusPoint(s, Number.MAX_SAFE_INTEGER);
          break;
        case "Enter":
        case " ":
          currentNav.onActivate?.(cursorRef.current.s, cursorRef.current.d);
          break;
        default:
          return;
      }
      event.preventDefault();
    };

    const onFocus = () => focusPoint(cursorRef.current.s, cursorRef.current.d);
    const onBlur = () => {
      const chart = chartRef.current;
      chart?.dispatchAction({ type: "hideTip" });
      chart?.dispatchAction({ type: "downplay" });
      setAnnouncement("");
    };
    return { onKeyDown, onFocus, onBlur };
  }, []);

  return (
    <div>
      <div
        ref={hostRef}
        role="img"
        aria-label={ariaLabel}
        tabIndex={nav === undefined ? -1 : 0}
        style={{ height }}
        data-testid={testId}
        {...(nav === undefined ? {} : keyHandlers)}
      />
      <p aria-live="polite" className="visually-hidden">
        {announcement}
      </p>
      {nav !== undefined && (
        <p className="visually-hidden">
          Use arrow keys to move between data points; Up and Down switch series
          {nav.onActivate !== undefined ? "; Enter opens the focused point" : ""}.
        </p>
      )}
    </div>
  );
}
