/**
 * Screen — Data Explorer.
 *
 * Browse the cleaned observations behind one route and period (`/v1/quotes`) and export
 * exactly the rows on screen. There is no bulk quote-level CSV endpoint in this API —
 * `/v1/export.csv` only serves published index series — so "export" here means
 * serializing the real, already-fetched rows, never synthesizing new ones.
 */

import { useMemo, useState } from "react";
import { useBasket, useQuotes } from "../api/hooks";
import { DataStatusBadge } from "../components/badges";
import { IconDatabase, IconDownload } from "../components/icons";
import { formatDate, formatINR, todayISO } from "../lib/format";

function monthStart(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

export default function DataExplorerScreen() {
  const basket = useBasket();
  const [route, setRoute] = useState("");
  const [period, setPeriod] = useState(monthStart(todayISO()));

  const effectiveRoute = route === "" ? (basket.data?.routes[0]?.code ?? "") : route;
  const quotes = useQuotes(effectiveRoute, period);

  const csvHref = useMemo(() => {
    if (quotes.data === undefined || quotes.data.items.length === 0) return null;
    const header = ["route", "travel_date", "advance_days", "carrier", "source", "total_fare", "currency", "treatment"];
    const rows = quotes.data.items.map((q) => [
      q.route_code,
      q.travel_date,
      String(q.advance_days),
      q.carrier_iata,
      q.source_code,
      String(q.total_fare),
      q.currency,
      q.is_outlier ? `outlier:${q.outlier_rule ?? ""}` : q.is_imputed ? `imputed:${q.imputation_method ?? ""}` : "clean",
    ]);
    const csv = [header, ...rows].map((r) => r.join(",")).join("\n");
    return `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`;
  }, [quotes.data]);

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="rounded-2xl border border-edge bg-surface p-6 shadow-card flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-accent-ink">
            <IconDatabase width={20} height={20} />
            <span className="text-xs font-bold uppercase tracking-wider">Public Microdata Surface</span>
          </div>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-ink">
            Standardized Airfare Data Explorer
          </h2>
          <p className="mt-1 text-xs text-ink-2 max-w-2xl">
            The cleaned observations one route-period's index value rests on, via{" "}
            <code className="font-mono">/v1/quotes</code> — each row's outlier and imputation
            treatment is shown, not hidden.
          </p>
        </div>

        {csvHref !== null && (
          <a
            href={csvHref}
            download={`apix_quotes_${effectiveRoute}_${period}.csv`}
            className="flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-xs font-bold text-navy shadow-sm hover:brightness-110 transition-colors"
          >
            <IconDownload width={15} height={15} />
            Export {quotes.data?.items.length ?? 0} rows shown
          </a>
        )}
      </div>

      {/* Filter Bar */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 rounded-2xl border border-edge bg-surface p-4 shadow-card">
        <div>
          <label className="block text-[11px] font-semibold text-ink-2 mb-1">Route</label>
          <select
            value={effectiveRoute}
            onChange={(e) => setRoute(e.target.value)}
            className="w-full rounded-lg border border-edge bg-raised px-2.5 py-1.5 text-xs font-medium text-ink"
          >
            {(basket.data?.routes ?? []).map((r) => (
              <option key={r.code} value={r.code}>
                {r.code}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-ink-2 mb-1">Period</label>
          <input
            type="month"
            value={period.slice(0, 7)}
            onChange={(e) => setPeriod(`${e.target.value}-01`)}
            className="w-full rounded-lg border border-edge bg-raised px-2.5 py-1.5 text-xs font-medium text-ink"
          />
        </div>
      </div>

      {/* Results Table */}
      <div className="rounded-2xl border border-edge bg-surface shadow-card overflow-hidden">
        <div className="px-5 py-3 border-b border-edge flex items-center justify-between">
          <span className="text-xs font-bold text-ink">
            Cleaned quotes — {effectiveRoute || "…"}, {period}
          </span>
          {quotes.data !== undefined && <DataStatusBadge status={quotes.data.meta.data_status} />}
        </div>

        {quotes.isLoading && <p className="px-5 py-6 text-xs text-ink-2">Loading…</p>}
        {quotes.error !== undefined && quotes.error !== null && (
          <p className="px-5 py-6 text-xs text-rose-600">Could not load quotes for this selection.</p>
        )}
        {quotes.data !== undefined && quotes.data.items.length === 0 && (
          <p className="px-5 py-6 text-xs text-ink-2">
            No quotes recorded for this route and period — an empty result, not an omission.
          </p>
        )}
        {quotes.data !== undefined && quotes.data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-ink">
              <thead className="bg-raised text-[11px] font-semibold text-ink-2 uppercase tracking-wider border-b border-edge/80">
                <tr>
                  <th className="px-5 py-3">Travel Date</th>
                  <th className="px-5 py-3">Advance</th>
                  <th className="px-5 py-3">Carrier</th>
                  <th className="px-5 py-3">Source</th>
                  <th className="px-5 py-3">Total Fare</th>
                  <th className="px-5 py-3">Treatment</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {quotes.data.items.map((q) => (
                  <tr key={q.quote_id} className="hover:bg-raised transition-colors">
                    <td className="px-5 py-3 font-mono">{formatDate(q.travel_date)}</td>
                    <td className="px-5 py-3 font-mono font-medium">T+{q.advance_days}</td>
                    <td className="px-5 py-3 font-bold text-accent-ink">{q.carrier_iata}</td>
                    <td className="px-5 py-3 font-mono">{q.source_code}</td>
                    <td className="px-5 py-3 font-mono font-bold text-ink">{formatINR(q.total_fare)}</td>
                    <td className="px-5 py-3">
                      {q.is_outlier ? (
                        <span className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold bg-rose-50 text-rose-700">
                          OUTLIER
                        </span>
                      ) : q.is_imputed ? (
                        <span className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold bg-amber-50 text-amber-700">
                          IMPUTED
                        </span>
                      ) : (
                        <span className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold bg-emerald-50 text-emerald-700">
                          CLEAN
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
