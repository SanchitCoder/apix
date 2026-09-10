/**
 * The panel every chart lives in. Owns the four states — loading, error, empty,
 * stale — and the chart/table toggle, so no screen improvises its own.
 *
 * "Stale" is rendered as a visible notice *above* a chart that still shows the last
 * complete data; the line is never drawn to zero to fake completeness.
 */

import { useId, useState } from "react";
import type { ReactNode } from "react";
import { ApiProblem } from "../api/client";
import { DataTable } from "./DataTable";
import type { TableSpec } from "./DataTable";
import { DataStatusBadge } from "./badges";
import { IconInbox } from "./icons";

interface ChartPanelProps {
  title: string;
  subtitle?: string;
  isLoading: boolean;
  error?: unknown;
  /** True when the request succeeded but there is nothing to draw. */
  isEmpty?: boolean;
  /** Why an empty result is empty — shown instead of a bare "no data". */
  emptyDetail?: string;
  /** Non-null renders a stale notice above the (still-drawn) chart. */
  stale?: string | null;
  /** meta.data_status from the API response backing this panel. */
  dataStatus?: string;
  table?: TableSpec;
  toolbar?: ReactNode;
  children: ReactNode;
}

export function ChartPanel({
  title,
  subtitle,
  isLoading,
  error,
  isEmpty = false,
  emptyDetail,
  stale = null,
  dataStatus,
  table,
  toolbar,
  children,
}: ChartPanelProps) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const headingId = useId();

  let body: ReactNode;
  if (isLoading) {
    body = (
      <div
        className="flex h-48 items-center justify-center text-sm text-ink-2"
        role="status"
        aria-live="polite"
      >
        Loading {title.toLowerCase()}…
      </div>
    );
  } else if (error !== undefined && error !== null) {
    const problem = error instanceof ApiProblem ? error : null;
    body = (
      <div role="alert" className="rounded-xl border border-critical-ink/30 bg-critical-soft p-4 text-sm">
        <p className="font-medium text-critical-ink">
          {problem !== null ? problem.title : "Request failed"}
        </p>
        <p className="mt-1 text-ink-2">
          {problem?.detail ?? (error instanceof Error ? error.message : String(error))}
        </p>
      </div>
    );
  } else if (isEmpty) {
    body = (
      <div className="flex h-48 flex-col items-center justify-center gap-2 text-sm">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-raised text-muted">
          <IconInbox width={20} height={20} />
        </span>
        <p className="font-medium">No data for this selection</p>
        <p className="text-ink-2">
          {emptyDetail ?? "The API returned an empty result — recorded as such, not a gap."}
        </p>
      </div>
    );
  } else {
    body = (
      <>
        {stale !== null && (
          <p className="mb-2 rounded-lg border border-warning-ink/30 bg-warning-soft px-3 py-2 text-sm text-warning-ink">
            <span aria-hidden="true">⚠ </span>
            {stale}
          </p>
        )}
        {view === "chart" || table === undefined ? children : <DataTable spec={table} />}
      </>
    );
  }

  const showToggle = !isLoading && (error === undefined || error === null) && !isEmpty;

  return (
    <section
      aria-labelledby={headingId}
      className="rounded-2xl border border-edge bg-surface p-5 shadow-card"
    >
      <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id={headingId} className="text-base font-semibold text-ink">
            {title}
          </h2>
          {subtitle !== undefined && <p className="mt-0.5 text-sm text-ink-2">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-2">
          {dataStatus !== undefined && <DataStatusBadge status={dataStatus} />}
          {toolbar}
          {showToggle && table !== undefined && (
            <button
              type="button"
              className="rounded-full border border-edge px-3 py-1 text-xs font-medium text-ink-2 transition-colors hover:border-accent hover:text-accent-ink"
              aria-pressed={view === "table"}
              onClick={() => setView(view === "chart" ? "table" : "chart")}
            >
              {view === "chart" ? "View as table" : "View as chart"}
            </button>
          )}
        </div>
      </header>
      {body}
    </section>
  );
}
