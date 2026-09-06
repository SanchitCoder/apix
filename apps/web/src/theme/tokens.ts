/**
 * The shared theme — the only place colours, type scale and grid values live.
 *
 * Every chart and panel reads from here; no per-chart colour literals anywhere else
 * (a lint-adjacent convention enforced by review, not tooling). The categorical order
 * is a colour-vision-deficiency safety mechanism validated with the dataviz palette
 * validator in both modes — do not reorder or insert hues without re-running it.
 */

export type ThemeMode = "light" | "dark";

export interface ThemeTokens {
  mode: ThemeMode;
  /** Page background behind panels. */
  page: string;
  /** Chart / panel surface. */
  surface: string;
  surfaceRaised: string;
  inkPrimary: string;
  inkSecondary: string;
  inkMuted: string;
  grid: string;
  axis: string;
  border: string;
  /** Categorical series colours, fixed order. Never cycled past 8. */
  series: readonly [string, string, string, string, string, string, string, string];
  /** Sequential ramp (one hue, light→dark) for magnitude. */
  sequential: readonly string[];
  /** Diverging: cool pole → neutral midpoint → warm pole, for deviation-from-zero. */
  divergingNeg: readonly string[];
  divergingMid: string;
  divergingPos: readonly string[];
  status: { good: string; warning: string; serious: string; critical: string };
  /** Emphasis colour for the headline series (categorical slot 1). */
  accent: string;
  fontFamily: string;
  fontFamilyMono: string;
  fontSize: { xs: number; sm: number; base: number; lg: number; xl: number };
}

const FONT = '"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif';
const FONT_MONO = '"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace';
const SIZES = { xs: 11, sm: 12, base: 13, lg: 16, xl: 22 } as const;

// Status colours are fixed across modes and never reused as series colours.
const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
} as const;

export const LIGHT: ThemeTokens = {
  mode: "light",
  page: "#eef2f8",
  surface: "#ffffff",
  surfaceRaised: "#ffffff",
  inkPrimary: "#0b0b0b",
  inkSecondary: "#52514e",
  inkMuted: "#898781",
  grid: "#e1e0d9",
  axis: "#c3c2b7",
  border: "rgba(11,11,11,0.10)",
  series: [
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#4a3aa7",
    "#e34948",
  ],
  sequential: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
  divergingNeg: ["#0d366b", "#1c5cab", "#3987e5", "#9ec5f4"],
  divergingMid: "#f0efec",
  divergingPos: ["#f2b8b8", "#e66767", "#d03b3b", "#8f1d1d"],
  status: STATUS,
  accent: "#2a78d6",
  fontFamily: FONT,
  fontFamilyMono: FONT_MONO,
  fontSize: SIZES,
};

export const DARK: ThemeTokens = {
  mode: "dark",
  page: "#0d0d0d",
  surface: "#1a1a19",
  surfaceRaised: "#232322",
  inkPrimary: "#ffffff",
  inkSecondary: "#c3c2b7",
  inkMuted: "#898781",
  grid: "#2c2c2a",
  axis: "#383835",
  border: "rgba(255,255,255,0.10)",
  series: [
    "#3987e5",
    "#d95926",
    "#199e70",
    "#c98500",
    "#d55181",
    "#008300",
    "#9085e9",
    "#e66767",
  ],
  sequential: ["#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"],
  divergingNeg: ["#cde2fb", "#6da7ec", "#3987e5", "#1c5cab"],
  divergingMid: "#383835",
  divergingPos: ["#7a2f2f", "#d03b3b", "#e66767", "#f2b8b8"],
  status: STATUS,
  accent: "#3987e5",
  fontFamily: FONT,
  fontFamilyMono: FONT_MONO,
  fontSize: SIZES,
};

export const tokensFor = (mode: ThemeMode): ThemeTokens => (mode === "dark" ? DARK : LIGHT);
