/**
 * Screen emblems for the page headers.
 *
 * These are not decorative stock art — each one is a miniature, honest rendition of the
 * chart grammar the screen actually uses (the same series colours, the same diverging
 * ramp, the same curve shapes), so the picture never claims a pattern the data doesn't
 * show. Hand-drawn SVG, no icon font, no photography, no image assets — consistent with
 * `icons.tsx` and the "no fabricated data" principle: nothing here is a coordinate, a
 * value or a boundary presented as real.
 */

import type { SVGProps } from "react";
import { useTheme } from "../theme/ThemeContext";
import { divergingRamp } from "../theme/echartsTheme";

type ArtProps = SVGProps<SVGSVGElement>;

const frame = {
  viewBox: "0 0 120 80",
  width: 120,
  height: 80,
  "aria-hidden": true,
} as const;

/** Index overview — the headline line against the dashed official-CPI comparator. */
export function OverviewArt(props: ArtProps) {
  const { tokens } = useTheme();
  return (
    <svg {...frame} {...props}>
      {[22, 42, 60].map((y) => (
        <line key={y} x1={8} y1={y} x2={112} y2={y} stroke={tokens.grid} strokeWidth={1} strokeDasharray="1 4" />
      ))}
      <path
        d="M8 54 C26 49 40 58 56 46 C74 32 92 40 112 26"
        fill="none"
        stroke={tokens.series[1]}
        strokeWidth={2}
        strokeDasharray="4 3"
        strokeLinecap="round"
      />
      <path
        d="M8 60 C24 50 38 54 52 36 C68 16 90 24 112 10"
        fill="none"
        stroke={tokens.series[0]}
        strokeWidth={3}
        strokeLinecap="round"
      />
      <circle cx={112} cy={10} r={4} fill={tokens.series[0]} stroke={tokens.surface} strokeWidth={1.5} />
    </svg>
  );
}

/** Route explorer — corridors between airport nodes, coloured on the momentum ramp. */
export function RouteExplorerArt(props: ArtProps) {
  const { tokens } = useTheme();
  const ramp = divergingRamp(tokens);
  const rising = ramp[ramp.length - 1] ?? tokens.series[0];
  const falling = ramp[0] ?? tokens.series[0];
  const nodes: [number, number][] = [
    [14, 58],
    [60, 16],
    [106, 50],
  ];
  return (
    <svg {...frame} {...props}>
      <path d="M14 58 Q37 20 60 16" fill="none" stroke={rising} strokeWidth={3} strokeLinecap="round" />
      <path d="M60 16 Q83 20 106 50" fill="none" stroke={tokens.axis} strokeWidth={3} strokeLinecap="round" />
      <path d="M14 58 Q60 76 106 50" fill="none" stroke={falling} strokeWidth={3} strokeLinecap="round" />
      {nodes.map(([x, y]) => (
        <circle key={`${x}-${y}`} cx={x} cy={y} r={5} fill={tokens.surface} stroke={tokens.axis} strokeWidth={1.75} />
      ))}
    </svg>
  );
}

/** Sector heatmap — a mosaic sample of the same diverging ramp the real grid uses. */
export function HeatmapArt(props: ArtProps) {
  const { tokens } = useTheme();
  const ramp = divergingRamp(tokens);
  const cols = 6;
  const rows = 3;
  const cell = 15;
  const gap = 3;
  const originX = (120 - (cols * cell + (cols - 1) * gap)) / 2;
  const originY = (80 - (rows * cell + (rows - 1) * gap)) / 2;
  const cells: { x: number; y: number; color: string }[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const t = (c - r * 0.6 + rows * 0.6) / (cols + rows * 0.6);
      const idx = Math.max(0, Math.min(ramp.length - 1, Math.round(t * (ramp.length - 1))));
      cells.push({
        x: originX + c * (cell + gap),
        y: originY + r * (cell + gap),
        color: ramp[idx] ?? tokens.divergingMid,
      });
    }
  }
  return (
    <svg {...frame} {...props}>
      {cells.map((cell_, i) => (
        <rect key={i} x={cell_.x} y={cell_.y} width={cell} height={cell} rx={2.5} fill={cell_.color} />
      ))}
    </svg>
  );
}

/** Lead-time curve — price falling toward departure, flattening past the inflection. */
export function LeadTimeArt(props: ArtProps) {
  const { tokens } = useTheme();
  return (
    <svg {...frame} {...props}>
      <path
        d="M10 16 C30 19 42 38 58 52 C72 63 92 65 112 65 L112 68 L10 68 Z"
        fill={tokens.series[0]}
        opacity={0.12}
      />
      <path
        d="M10 16 C30 19 42 38 58 52 C72 63 92 65 112 65"
        fill="none"
        stroke={tokens.series[0]}
        strokeWidth={3}
        strokeLinecap="round"
      />
      <circle cx={58} cy={52} r={4.5} fill={tokens.status.warning} stroke={tokens.surface} strokeWidth={2} />
    </svg>
  );
}

/** Method console — tunable parameters, drawn as an instrument panel of sliders. */
export function MethodConsoleArt(props: ArtProps) {
  const { tokens } = useTheme();
  const tracks: [number, number, string][] = [
    [30, 46, tokens.series[0]],
    [60, 22, tokens.series[2]],
    [90, 56, tokens.series[3]],
  ];
  return (
    <svg {...frame} {...props}>
      {tracks.map(([x]) => (
        <line key={x} x1={x} y1={14} x2={x} y2={66} stroke={tokens.grid} strokeWidth={4} strokeLinecap="round" />
      ))}
      {tracks.map(([x, y, color]) => (
        <circle key={x} cx={x} cy={y} r={6} fill={color} stroke={tokens.surface} strokeWidth={2} />
      ))}
    </svg>
  );
}

/** Audit & provenance — a source record with the traceability seal. */
export function AuditArt(props: ArtProps) {
  const { tokens } = useTheme();
  return (
    <svg {...frame} {...props}>
      <rect x={26} y={10} width={52} height={60} rx={4} fill={tokens.surface} stroke={tokens.axis} strokeWidth={1.75} />
      {[26, 36, 46].map((y) => (
        <line key={y} x1={34} y1={y} x2={70} y2={y} stroke={tokens.grid} strokeWidth={2.5} strokeLinecap="round" />
      ))}
      <line x1={34} y1={56} x2={56} y2={56} stroke={tokens.grid} strokeWidth={2.5} strokeLinecap="round" />
      <circle cx={84} cy={58} r={17} fill={tokens.accent} opacity={0.14} />
      <circle cx={84} cy={58} r={17} fill="none" stroke={tokens.accent} strokeWidth={2} />
      <path
        d="M76 58 l5.5 5.5 L93 51"
        fill="none"
        stroke={tokens.accent}
        strokeWidth={2.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
