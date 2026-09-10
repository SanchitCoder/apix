/**
 * Data Explorer Card
 *
 * Links to the real observation-level surfaces only: `/v1/export.csv` (a flat download
 * of the headline series, the same endpoint `apps/api` actually serves) and the full
 * Data Explorer screen for filtering by route and period. No synthetic rows are
 * generated here — a downloaded file must trace back to real fare quotes.
 */

import { Link } from "react-router-dom";
import { BASE_URL, HEADLINE_SERIES } from "../api/client";
import { IconDatabase, IconDownload } from "./icons";

const CSV_URL = `${BASE_URL}/v1/export.csv?series=${encodeURIComponent(HEADLINE_SERIES)}`;

export function DataExplorerCard() {
  return (
    <div className="flex h-full flex-col justify-between rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_2px_12px_rgba(0,0,0,0.03)] transition-all hover:shadow-[0_4px_16px_rgba(0,0,0,0.06)]">
      <div>
        <div className="flex items-start gap-2.5">
          <div className="mt-0.5 text-blue-600">
            <IconDatabase width={18} height={18} />
          </div>
          <div>
            <h3 className="text-base font-bold text-slate-900">Data Explorer</h3>
            <p className="text-xs text-slate-500">Browse and download standardized airfare observations</p>
          </div>
        </div>
        <p className="mt-3 text-xs text-slate-500 leading-relaxed">
          Every row carries the index run and data status it was produced under, so a file
          stays traceable once it leaves this dashboard.
        </p>
      </div>

      <div className="mt-4 flex flex-col gap-2 pt-2">
        <Link
          to="/explorer"
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 py-2.5 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-blue-700"
        >
          Open Data Explorer
        </Link>
        <a
          href={CSV_URL}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white py-2.5 text-xs font-semibold text-slate-700 shadow-sm transition-colors hover:bg-slate-50"
        >
          <IconDownload width={14} height={14} />
          Download Headline CSV
        </a>
      </div>
    </div>
  );
}
