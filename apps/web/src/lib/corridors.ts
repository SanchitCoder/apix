/**
 * Builds RouteMap corridors from the routes and heatmap responses: momentum is the
 * latest period's change over the previous one, per route.
 *
 * Limited to routes with known airport coordinates (see RouteMap's own note on why —
 * db/seeds/airports.csv doesn't cover the full basket yet).
 */

import type { HeatmapCell, RouteSummary } from "../api/client";
import type { CorridorPoint } from "../components/RouteMap";

export function buildCorridors(
  routes: RouteSummary[] | undefined,
  heatmap: HeatmapCell[] | undefined,
): CorridorPoint[] {
  if (routes === undefined || heatmap === undefined) return [];
  return routes.flatMap((route) => {
    if (
      route.origin_lat === null ||
      route.origin_lat === undefined ||
      route.origin_lon === null ||
      route.origin_lon === undefined ||
      route.dest_lat === null ||
      route.dest_lat === undefined ||
      route.dest_lon === null ||
      route.dest_lon === undefined
    ) {
      return [];
    }
    const cells = heatmap
      .filter((c) => c.route_code === route.code)
      .sort((a, b) => a.period.localeCompare(b.period));
    const latest = cells.at(-1);
    const previous = cells.at(-2);
    const momentumPct =
      latest !== undefined && previous !== undefined
        ? ((latest.value - previous.value) / previous.value) * 100
        : 0;
    return [
      {
        code: route.code,
        originIata: route.origin_iata,
        originLat: route.origin_lat,
        originLon: route.origin_lon,
        destIata: route.dest_iata,
        destLat: route.dest_lat,
        destLon: route.dest_lon,
        momentumPct,
      },
    ];
  });
}
