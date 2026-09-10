/**
 * Largest period-over-period movers across the basket, for the dashboard's "Notable
 * movers" panel. Same arithmetic as `corridors.ts`'s momentum (latest vs. previous
 * period, per route) but over every route in the heatmap response, not only the ones
 * with known airport coordinates — this panel draws no map, so it isn't limited by
 * `db/seeds/airports.csv` coverage the way `RouteMap` is.
 */

import type { HeatmapCell } from "../api/client";

export interface Mover {
  routeCode: string;
  momentumPct: number;
  latestValue: number;
  latestPeriod: string;
}

export function computeMovers(heatmap: HeatmapCell[] | undefined, limit = 4): Mover[] {
  if (heatmap === undefined) return [];
  const byRoute = new Map<string, HeatmapCell[]>();
  for (const cell of heatmap) {
    const list = byRoute.get(cell.route_code);
    if (list === undefined) byRoute.set(cell.route_code, [cell]);
    else list.push(cell);
  }
  const movers: Mover[] = [];
  for (const [routeCode, cells] of byRoute) {
    const sorted = [...cells].sort((a, b) => a.period.localeCompare(b.period));
    const latest = sorted.at(-1);
    const previous = sorted.at(-2);
    if (latest === undefined || previous === undefined) continue;
    movers.push({
      routeCode,
      momentumPct: ((latest.value - previous.value) / previous.value) * 100,
      latestValue: latest.value,
      latestPeriod: latest.period,
    });
  }
  return movers.sort((a, b) => Math.abs(b.momentumPct) - Math.abs(a.momentumPct)).slice(0, limit);
}
