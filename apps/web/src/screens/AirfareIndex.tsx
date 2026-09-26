/**
 * Screen — Airfare Index
 */

import { lazy, Suspense } from "react";
const SectorHeatmap = lazy(() => import("./SectorHeatmap"));

export default function AirfareIndex() {
  return (
    <div className="flex flex-col gap-6">
      <Suspense fallback={<p className="text-xs text-ink-2">Loading Index View…</p>}>
        <SectorHeatmap />
      </Suspense>
    </div>
  );
}
