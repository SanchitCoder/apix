/** Period-over-period and year-over-year change, computed only when the history exists. */

import type { IndexPoint } from "../api/client";

export interface SeriesChange {
  label: string;
  pct: number | null;
  /** Why `pct` is null — shown instead of a fabricated number. */
  unavailableReason?: string;
}

/**
 * Month-over-month and year-over-year change for a monthly series.
 *
 * A change is reported only when both endpoints exist in the series already returned;
 * it is never interpolated or estimated from a shorter window. Fewer than 13 monthly
 * points means no year-over-year comparison is possible yet, and that is stated rather
 * than silently omitted.
 */
export function computeChanges(points: IndexPoint[]): { mom: SeriesChange; yoy: SeriesChange } {
  const sorted = [...points].sort((a, b) => a.period.localeCompare(b.period));
  const latest = sorted.at(-1);
  const previous = sorted.at(-2);
  const mom: SeriesChange =
    latest !== undefined && previous !== undefined
      ? { label: "vs previous month", pct: ((latest.value - previous.value) / previous.value) * 100 }
      : { label: "vs previous month", pct: null, unavailableReason: "fewer than two periods returned" };

  const yearAgo = sorted.find((p) => p.period === shiftMonths(latest?.period ?? "", -12));
  const yoy: SeriesChange =
    latest !== undefined && yearAgo !== undefined
      ? { label: "vs 12 months ago", pct: ((latest.value - yearAgo.value) / yearAgo.value) * 100 }
      : {
          label: "vs 12 months ago",
          pct: null,
          unavailableReason: "fewer than 13 months of published history",
        };

  return { mom, yoy };
}

function shiftMonths(isoDate: string, delta: number): string {
  if (isoDate === "") return "";
  const date = new Date(`${isoDate}T00:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + delta);
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  return `${date.getUTCFullYear()}-${month}-01`;
}
