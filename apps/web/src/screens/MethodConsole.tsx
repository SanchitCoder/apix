/**
 * Screen 5 — Method console. The differentiator: controls bound to config/method.yaml,
 * each change recomputed against a live preview run via POST /v1/method/preview.
 *
 * The preview is never confused with a published run: its own `config_hash` is shown,
 * distinct from the method in force, and the chart always draws the baseline alongside
 * it so a reviewer sees exactly what a setting moved.
 */

import { useEffect, useMemo, useState } from "react";
import { useMethod, useMethodPreview } from "../api/hooks";
import type { MethodOverrides } from "../api/client";
import { ChartPanel } from "../components/ChartPanel";
import { EChart } from "../components/EChart";
import { MethodConsoleArt } from "../components/illustrations";
import { PageHeader } from "../components/PageHeader";
import { formatCount, formatIndex, formatPeriod } from "../lib/format";
import { useTheme } from "../theme/ThemeContext";
import {
  baseOption,
  gridDefaults,
  legendDefaults,
  timeAxis,
  tooltipDefaults,
  valueAxis,
} from "../theme/echartsTheme";

// Mirrors packages/apix_core/src/apix_core/config/method.py. Carli is listed because
// the enum accepts it — the server rejects it as an unpublishable method (422), and the
// console surfaces that rejection rather than silently refusing to offer the option.
const ELEMENTARY_FORMULAS = ["jevons", "dutot", "carli"] as const;
const MULTILATERAL_METHODS = [
  "geks_tornqvist",
  "geks_fisher",
  "time_product_dummy",
  "geary_khamis",
] as const;
const SPLICE_METHODS = ["movement", "window", "half", "mean"] as const;
const IMPUTATION_RULES = ["none", "carry_forward", "class_mean", "targeted_mean"] as const;

interface ControlState {
  elementary_formula: (typeof ELEMENTARY_FORMULAS)[number];
  multilateral_method: (typeof MULTILATERAL_METHODS)[number];
  window_length_periods: number;
  splice_method: (typeof SPLICE_METHODS)[number];
  quality_adjustment_enabled: boolean;
  imputation_rule: (typeof IMPUTATION_RULES)[number];
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="block text-sm font-medium text-ink-2">
        {label}
      </label>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

const selectClass =
  "w-full rounded-lg border border-edge bg-raised px-3 py-2 text-sm text-ink transition-colors focus:border-accent";

export default function MethodConsole() {
  const { tokens } = useTheme();
  const method = useMethod();
  const [controls, setControls] = useState<ControlState | null>(null);

  useEffect(() => {
    if (method.data === undefined || controls !== null) return;
    setControls({
      elementary_formula: method.data.elementary_formula as ControlState["elementary_formula"],
      multilateral_method: method.data.multilateral_method as ControlState["multilateral_method"],
      window_length_periods: method.data.window_length_periods,
      splice_method: method.data.splice_method as ControlState["splice_method"],
      quality_adjustment_enabled: method.data.quality_adjustment_enabled,
      imputation_rule: method.data.imputation_rule as ControlState["imputation_rule"],
    });
  }, [method.data, controls]);

  const overrides: MethodOverrides = controls ?? {};
  const preview = useMethodPreview(overrides);
  const previewProblem =
    preview.error !== null && preview.error !== undefined ? preview.error : undefined;

  const option = useMemo(() => {
    if (preview.data === undefined) return null;
    const periods = preview.data.points.map((p) => formatPeriod(p.period));
    return {
      ...baseOption(tokens),
      grid: gridDefaults(),
      tooltip: tooltipDefaults(tokens),
      legend: legendDefaults(tokens),
      xAxis: { ...timeAxis(tokens), data: periods },
      yAxis: valueAxis(tokens, "Index (ref. period = 100)"),
      series: [
        {
          name: "Method in force",
          type: "line" as const,
          data: preview.data.points.map((p) => p.baseline_value),
          lineStyle: { width: 2, color: tokens.inkMuted, type: "dashed" as const },
          itemStyle: { color: tokens.inkMuted },
          showSymbol: false,
        },
        {
          name: preview.data.is_baseline ? "Preview (matches method in force)" : "Preview",
          type: "line" as const,
          data: preview.data.points.map((p) => p.value),
          lineStyle: { width: 2, color: tokens.series[0] },
          itemStyle: { color: tokens.series[0] },
          showSymbol: false,
        },
      ],
    };
  }, [preview.data, tokens]);

  const nav = useMemo(() => {
    if (preview.data === undefined) return undefined;
    const points = preview.data.points;
    return {
      seriesCount: 2,
      pointCount: () => points.length,
      describe: (s: number, d: number) => {
        const point = points[d];
        if (point === undefined) return "";
        const value = s === 0 ? point.baseline_value : point.value;
        const label = s === 0 ? "Method in force" : "Preview";
        return `${label}, ${formatPeriod(point.period)}: ${formatIndex(value)}.`;
      },
    };
  }, [preview.data]);

  const table = useMemo(() => {
    if (preview.data === undefined) return undefined;
    return {
      caption: "Preview index run vs. the method in force, by period",
      columns: ["Period", "Method in force", "Preview", "Quotes", "Imputed cells", "Outlier cells"],
      rows: preview.data.points.map((p) => [
        formatPeriod(p.period),
        formatIndex(p.baseline_value),
        formatIndex(p.value),
        formatCount(p.n_quotes),
        String(p.imputed_cells),
        String(p.outlier_cells),
      ]),
    };
  }, [preview.data]);

  if (controls === null) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          title="Method console"
          subtitle="Controls bound to config/method.yaml, recomputed against a live preview run — never confused with a published run."
          art={<MethodConsoleArt />}
        />
        <p className="p-6 text-sm text-ink-2" role="status">
          Loading the method in force…
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Method console"
        subtitle="Controls bound to config/method.yaml, recomputed against a live preview run — never confused with a published run."
        art={<MethodConsoleArt />}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr]">
        <form
          aria-label="Method controls"
          className="flex flex-col gap-4 rounded-2xl border border-edge bg-surface p-5 shadow-card"
          onSubmit={(e) => e.preventDefault()}
        >
          <Field label="Elementary formula" htmlFor="mc-elementary">
            <select
              id="mc-elementary"
              className={selectClass}
              value={controls.elementary_formula}
              onChange={(e) =>
                setControls({ ...controls, elementary_formula: e.target.value as ControlState["elementary_formula"] })
              }
            >
              {ELEMENTARY_FORMULAS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </Field>
  
          <Field label="Multilateral method" htmlFor="mc-multilateral">
            <select
              id="mc-multilateral"
              className={selectClass}
              value={controls.multilateral_method}
              onChange={(e) =>
                setControls({ ...controls, multilateral_method: e.target.value as ControlState["multilateral_method"] })
              }
            >
              {MULTILATERAL_METHODS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>
  
          <Field label={`Window length: ${controls.window_length_periods} periods`} htmlFor="mc-window">
            <input
              id="mc-window"
              type="range"
              min={2}
              max={48}
              value={controls.window_length_periods}
              onChange={(e) => setControls({ ...controls, window_length_periods: Number(e.target.value) })}
              className="w-full accent-accent"
            />
          </Field>
  
          <Field label="Splice method" htmlFor="mc-splice">
            <select
              id="mc-splice"
              className={selectClass}
              value={controls.splice_method}
              onChange={(e) => setControls({ ...controls, splice_method: e.target.value as ControlState["splice_method"] })}
            >
              {SPLICE_METHODS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
  
          <Field label="Imputation rule" htmlFor="mc-imputation">
            <select
              id="mc-imputation"
              className={selectClass}
              value={controls.imputation_rule}
              onChange={(e) => setControls({ ...controls, imputation_rule: e.target.value as ControlState["imputation_rule"] })}
            >
              {IMPUTATION_RULES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </Field>
  
          <div className="flex items-center gap-2">
            <input
              id="mc-quality"
              type="checkbox"
              checked={controls.quality_adjustment_enabled}
              onChange={(e) => setControls({ ...controls, quality_adjustment_enabled: e.target.checked })}
              className="h-4 w-4 accent-accent"
            />
            <label htmlFor="mc-quality" className="text-sm text-ink">
              Quality adjustment enabled
            </label>
          </div>
  
          {method.data !== undefined && (
            <button
              type="button"
              className="rounded-full border border-edge px-3 py-1.5 text-sm font-medium text-ink-2 transition-colors hover:border-accent hover:text-accent-ink"
              onClick={() =>
                setControls({
                  elementary_formula: method.data.elementary_formula as ControlState["elementary_formula"],
                  multilateral_method: method.data.multilateral_method as ControlState["multilateral_method"],
                  window_length_periods: method.data.window_length_periods,
                  splice_method: method.data.splice_method as ControlState["splice_method"],
                  quality_adjustment_enabled: method.data.quality_adjustment_enabled,
                  imputation_rule: method.data.imputation_rule as ControlState["imputation_rule"],
                })
              }
            >
              Reset to method in force
            </button>
          )}
        </form>
  
        <div className="flex flex-col gap-4">
          <ChartPanel
            title="Preview index run"
            subtitle="Dashed line is the published method's series; solid is the preview under the controls at left."
            isLoading={preview.isLoading}
            error={previewProblem}
            dataStatus={preview.data?.meta.data_status}
            table={table}
          >
            {option !== null && (
              <EChart
                option={option}
                height={320}
                ariaLabel="Line chart comparing the method-in-force index series to a live preview run under the selected method controls"
                nav={nav}
              />
            )}
          </ChartPanel>
  
          {preview.data !== undefined && (
            <dl aria-label="Preview diagnostics" className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              {[
                ["Coverage", `${preview.data.diagnostics.coverage_pct.toFixed(0)}%`],
                ["Quotes", formatCount(preview.data.diagnostics.n_quotes)],
                ["Imputed cells", String(preview.data.diagnostics.imputed_cell_count)],
                ["Outliers dropped", String(preview.data.diagnostics.outlier_dropped_count)],
                ["Suppressed cells", String(preview.data.diagnostics.suppressed_cell_count)],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl border border-edge bg-surface p-3 shadow-card">
                  <dt className="text-xs text-ink-2">{label}</dt>
                  <dd className="mt-0.5 font-mono text-lg font-semibold tabular-nums text-ink">{value}</dd>
                </div>
              ))}
            </dl>
          )}
  
          {preview.data !== undefined && (
            <p className="text-xs text-ink-2">
              Preview config hash:{" "}
              <code className="rounded bg-raised px-1.5 py-0.5 font-mono text-ink">
                {preview.data.config_hash.slice(0, 16)}…
              </code>
              {preview.data.is_baseline ? " (matches the method in force)" : ""}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
