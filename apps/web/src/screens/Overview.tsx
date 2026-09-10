/**
 * Overview Dashboard.
 *
 * Same card-grid layout as the design pass, rebuilt on real endpoints only: the
 * headline index and its month-over-month change, notable movers computed from the
 * heatmap (no model, no generated text), route and lead-time previews for the picked
 * corridor, the route-momentum map, today's per-source collection status, and honest
 * entry points into the CSV export and API docs. Nothing here renders a number that
 * doesn't trace back to `/v1/*`.
 */

import { useMemo, useState } from "react";
import { HEADLINE_SERIES } from "../api/client";
import {
  useBasket,
  useCarriers,
  useCoverage,
  useHeatmap,
  useIndexSeries,
  useMethodPreview,
  useRoutes,
} from "../api/hooks";
import { CoverageStrip } from "../components/CoverageStrip";
import { CoverageTile } from "../components/CoverageTile";
import { DataExplorerCard } from "../components/DataExplorerCard";
import { HeroIndexCard } from "../components/HeroIndexCard";
import { IconDatabase, IconNetwork, IconPlane } from "../components/icons";
import { LeadTimeBarsPanel } from "../components/LeadTimeBarsPanel";
import { MoversPanel } from "../components/MoversPanel";
import { RouteAnalysisPanel } from "../components/RouteAnalysisPanel";
import { RouteMap } from "../components/RouteMap";
import { StatTile } from "../components/StatTile";
import { Toolbar } from "../components/Toolbar";
import type { ToolbarValue } from "../components/Toolbar";
import { buildCorridors } from "../lib/corridors";
import { computeMovers } from "../lib/movers";
import { formatCount, formatDate, todayISO } from "../lib/format";

export default function Overview() {
  const headline = useIndexSeries(HEADLINE_SERIES);
  const headlinePreview = useMethodPreview({});
  const basket = useBasket();
  const carriers = useCarriers();
  const routes = useRoutes();
  const heatmap = useHeatmap();
  const coverage = useCoverage(todayISO());

  const [filter, setFilter] = useState<ToolbarValue>({ route: "DEL-BOM", date: todayISO(), carrier: "" });

  const corridors = useMemo(
    () => buildCorridors(routes.data?.items, heatmap.data?.items),
    [routes.data, heatmap.data],
  );
  const movers = useMemo(() => computeMovers(heatmap.data?.items), [heatmap.data]);

  const observationsToday = coverage.data?.sources.reduce((sum, s) => sum + s.quotes_collected, 0);

  return (
    <div className="flex flex-col gap-6">
      <Toolbar
        routes={basket.data?.routes ?? []}
        carriers={carriers.data?.carriers ?? []}
        value={filter}
        onApply={setFilter}
      />

      {/* Row 1: Headline index & notable movers */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <HeroIndexCard
            items={headline.data?.items}
            isLoading={headline.isLoading}
            error={headline.error}
            preview={
              headlinePreview.error
                ? undefined
                : {
                    value: headlinePreview.data?.points[0]?.baseline_value ?? 0,
                    nQuotes: headlinePreview.data?.points[0]?.n_quotes ?? 0,
                    formula: headlinePreview.data?.settings.elementary_formula ?? "",
                    isLoading: headlinePreview.isLoading,
                  }
            }
          />
        </div>
        <div className="lg:col-span-4 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_2px_12px_rgba(0,0,0,0.03)]">
          <h2 className="text-base font-bold text-slate-900">Notable movers</h2>
          <p className="mt-0.5 text-xs text-slate-500">Largest period-over-period change, from /v1/heatmap.</p>
          <div className="mt-4">
            {heatmap.isLoading ? (
              <p className="text-xs text-slate-500">Loading…</p>
            ) : (
              <MoversPanel movers={movers} />
            )}
          </div>
        </div>
      </div>

      {/* Row 2: KPI tiles */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile
          index={0}
          icon={<IconPlane width={18} height={18} />}
          label="Routes in basket"
          value={basket.data === undefined ? "…" : String(basket.data.routes.length)}
        />
        <StatTile
          index={1}
          icon={<IconDatabase width={18} height={18} />}
          label="Fare observations today"
          value={observationsToday === undefined ? "…" : formatCount(observationsToday)}
        />
        <StatTile
          index={2}
          icon={<IconNetwork width={18} height={18} />}
          label="Data sources"
          value={coverage.data === undefined ? "…" : String(coverage.data.sources.length)}
        />
        <StatTile
          index={3}
          label="Coverage date"
          value={coverage.data === undefined ? "…" : formatDate(coverage.data.date)}
        />
        {coverage.data !== undefined && <CoverageTile pct={coverage.data.coverage_pct} index={4} />}
      </div>

      {/* Row 3: Route analysis, lead time, route map — all scoped to the toolbar's route */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <RouteAnalysisPanel routeCode={filter.route} />
        <LeadTimeBarsPanel routeCode={filter.route} carrier={filter.carrier} />
        <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_2px_12px_rgba(0,0,0,0.03)]">
          <h2 className="text-base font-bold text-slate-900">Route momentum</h2>
          <p className="mt-0.5 text-xs text-slate-500">Corridors coloured by change vs. the previous period.</p>
          <div className="mt-3">
            {routes.isLoading || heatmap.isLoading ? (
              <p className="text-xs text-slate-500">Loading…</p>
            ) : corridors.length === 0 ? (
              <p className="text-xs text-slate-500">No routes with known airport coordinates in the current basket.</p>
            ) : (
              <RouteMap corridors={corridors} compact />
            )}
          </div>
        </div>
      </div>

      {/* Row 4: today's source status, data export */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_2px_12px_rgba(0,0,0,0.03)]">
          <h2 className="text-base font-bold text-slate-900">Source status — today</h2>
          <p className="mt-0.5 text-xs text-slate-500">Per-source collection status, PolicyEngine-gated.</p>
          <div className="mt-3">
            {coverage.isLoading ? (
              <p className="text-xs text-slate-500">Loading…</p>
            ) : coverage.data !== undefined ? (
              <CoverageStrip coverage={coverage.data} />
            ) : null}
          </div>
        </div>
        <DataExplorerCard />
      </div>
    </div>
  );
}
