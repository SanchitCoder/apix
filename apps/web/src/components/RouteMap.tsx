/**
 * Corridors coloured by momentum — a schematic equirectangular projection, not a basemap.
 *
 * There is no India GeoJSON asset available to this build, so the map draws airport
 * nodes at their real lat/lon (db/seeds/airports.csv) on a simple lon/lat -> SVG
 * projection scoped to the routes in view, and colours each corridor by its momentum
 * (period-over-period change of the route index) on the shared diverging ramp. It is
 * honest about being schematic: axes are not shown, only relative position.
 */

import { useId, useMemo } from "react";
import { useTheme } from "../theme/ThemeContext";
import { divergingRamp } from "../theme/echartsTheme";
import { formatPct } from "../lib/format";

export interface CorridorPoint {
  code: string;
  originIata: string;
  originLat: number;
  originLon: number;
  destIata: string;
  destLat: number;
  destLon: number;
  momentumPct: number;
}

const WIDTH = 640;
const HEIGHT = 360;
// A squarer variant for narrow-column placements (e.g. the Overview dashboard): the
// full-width HEIGHT ratio, scaled into a third of the page width, leaves so little
// vertical room that airport labels become illegible — this trades width-efficiency
// for enough height that the map stays readable.
const HEIGHT_COMPACT = 480;
const PAD = 48;

function colorForMomentum(pct: number, ramp: string[]): string {
  // Clamp to +/-6% and map onto the diverging ramp; 0% lands on the neutral midpoint.
  const clamped = Math.max(-6, Math.min(6, pct));
  const t = (clamped + 6) / 12; // 0..1
  const index = Math.round(t * (ramp.length - 1));
  return ramp[index] ?? ramp[Math.floor(ramp.length / 2)] ?? "#888";
}

export function RouteMap({ corridors, compact = false }: { corridors: CorridorPoint[]; compact?: boolean }) {
  const { tokens } = useTheme();
  const titleId = useId();
  const ramp = useMemo(() => divergingRamp(tokens), [tokens]);
  const height = compact ? HEIGHT_COMPACT : HEIGHT;

  const bounds = useMemo(() => {
    const lats = corridors.flatMap((c) => [c.originLat, c.destLat]);
    const lons = corridors.flatMap((c) => [c.originLon, c.destLon]);
    return {
      minLat: Math.min(...lats),
      maxLat: Math.max(...lats),
      minLon: Math.min(...lons),
      maxLon: Math.max(...lons),
    };
  }, [corridors]);

  const project = (lat: number, lon: number): [number, number] => {
    const latSpan = bounds.maxLat - bounds.minLat || 1;
    const lonSpan = bounds.maxLon - bounds.minLon || 1;
    const x = PAD + ((lon - bounds.minLon) / lonSpan) * (WIDTH - 2 * PAD);
    // SVG y grows downward; latitude grows northward.
    const y = height - PAD - ((lat - bounds.minLat) / latSpan) * (height - 2 * PAD);
    return [x, y];
  };

  const airports = useMemo(() => {
    const seen = new Map<string, { lat: number; lon: number }>();
    for (const c of corridors) {
      seen.set(c.originIata, { lat: c.originLat, lon: c.originLon });
      seen.set(c.destIata, { lat: c.destLat, lon: c.destLon });
    }
    return [...seen.entries()];
  }, [corridors]);

  return (
    <div>
      {/* Capping by width, not height: an SVG replaced-element clamped only via
          max-height keeps its full CSS width and either stretches or letterboxes
          unpredictably across browsers once the column goes full-bleed at narrower
          breakpoints. A width cap is the one dimension every browser honours the same
          way, and the intrinsic viewBox ratio does the rest. */}
      <svg
        role="img"
        aria-labelledby={titleId}
        viewBox={`0 0 ${WIDTH} ${height}`}
        className={compact ? "mx-auto block w-full max-w-[480px]" : "w-full"}
        style={compact ? undefined : { maxHeight: height }}
      >
        <title id={titleId}>
          Schematic map of {corridors.length} route corridors, coloured by momentum
        </title>
        {/* Graticule — reference lines at even fractions of the same lon/lat bounds the
            corridors themselves are projected against, not a basemap. It gives the eye a
            sense of scale without claiming a coastline this build has no data for. */}
        <g aria-hidden="true" opacity={0.5}>
          {[0.25, 0.5, 0.75].map((f) => (
            <line
              key={`v${f}`}
              x1={PAD + f * (WIDTH - 2 * PAD)}
              y1={PAD}
              x2={PAD + f * (WIDTH - 2 * PAD)}
              y2={height - PAD}
              stroke={tokens.grid}
              strokeWidth={1}
              strokeDasharray="1 5"
            />
          ))}
          {[0.33, 0.66].map((f) => (
            <line
              key={`h${f}`}
              x1={PAD}
              y1={PAD + f * (height - 2 * PAD)}
              x2={WIDTH - PAD}
              y2={PAD + f * (height - 2 * PAD)}
              stroke={tokens.grid}
              strokeWidth={1}
              strokeDasharray="1 5"
            />
          ))}
        </g>
        {corridors.map((c) => {
          const [x1, y1] = project(c.originLat, c.originLon);
          const [x2, y2] = project(c.destLat, c.destLon);
          const color = colorForMomentum(c.momentumPct, ramp);
          const midX = (x1 + x2) / 2;
          const midY = (y1 + y2) / 2;
          const bearing = (Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI;
          return (
            <g key={c.code}>
              <line
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={color}
                strokeWidth={3}
                strokeLinecap="round"
              >
                <title>
                  {c.code}: {formatPct(c.momentumPct)} vs previous period
                </title>
              </line>
              {/* A small aircraft mark riding the corridor midpoint, oriented along the
                  origin-to-destination bearing — the route itself, not a decoration. */}
              <path
                d="M-6 0 L5 -3.4 L2 0 L5 3.4 Z"
                fill={color}
                transform={`translate(${midX} ${midY}) rotate(${bearing})`}
              />
            </g>
          );
        })}
        {airports.map(([iata, pos]) => {
          const [x, y] = project(pos.lat, pos.lon);
          return (
            <g key={iata}>
              <circle cx={x} cy={y} r={5} fill={tokens.surfaceRaised} stroke={tokens.axis} strokeWidth={1.5}>
                <title>{iata}</title>
              </circle>
              {!compact && (
                <text
                  x={x}
                  y={y - 10}
                  textAnchor="middle"
                  fontSize={11}
                  fontFamily={tokens.fontFamily}
                  fill={tokens.inkSecondary}
                >
                  {iata}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <ul className="mt-3 flex flex-wrap gap-2 text-xs text-ink-2" aria-label="Corridor momentum legend">
        <li className="flex items-center gap-1.5 rounded-full border border-edge bg-raised px-2.5 py-1">
          <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: ramp[0] }} />
          Falling
        </li>
        <li className="flex items-center gap-1.5 rounded-full border border-edge bg-raised px-2.5 py-1">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: tokens.divergingMid }}
          />
          Flat
        </li>
        <li className="flex items-center gap-1.5 rounded-full border border-edge bg-raised px-2.5 py-1">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: ramp[ramp.length - 1] }}
          />
          Rising
        </li>
      </ul>
    </div>
  );
}
