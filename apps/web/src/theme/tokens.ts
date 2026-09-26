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

// Status colours are never reused as series colours, and each mode's four hues carry
// the same meaning (good = rising/compliant, critical = falling/breached, ...) — but
// the literal inks are tuned per mode, not copied verbatim, because the same hex that
// reads clearly as "dark ink on a near-white card" turns muddy and low-contrast as
// "dark ink on a near-black terminal surface." LIGHT keeps the original inks; DARK
// (below) lightens each one for the same contrast job against a much darker ground.
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

// The terminal palette: a near-black navy ground (not pure black — a trading-desk
// monitor at night is still blue-black, never neutral grey), a mint/teal brand accent
// or the amber-on-charcoal cousin of it, and the same fixed STATUS pair every mode
// uses for up/down semantics. Categorical `series` keeps the validated CVD-safe order
// from LIGHT's hues, just re-lit for a dark ground — do not reorder or insert hues
// without re-running the dataviz palette validator.
export const DARK: ThemeTokens = {
  mode: "dark",
  page: "#080b12",
  surface: "#0d121c",
  surfaceRaised: "#111827",
  inkPrimary: "#e7ecf5",
  inkSecondary: "#8a94a6",
  inkMuted: "#5b6472",
  grid: "#1b2331",
  axis: "#263041",
  border: "rgba(148,163,184,0.14)",
  series: [
    "#3ee6b4",
    "#eb6834",
    "#5b9cf6",
    "#eda100",
    "#e87ba4",
    "#4fd67a",
    "#9085e9",
    "#e66767",
  ],
  sequential: ["#062e26", "#0a4a3c", "#106b57", "#189173", "#3ee6b4", "#8ff3d3", "#d4faec"],
  divergingNeg: ["#d4faec", "#8ff3d3", "#3ee6b4", "#106b57"],
  divergingMid: "#263041",
  divergingPos: ["#7a2f2f", "#d03b3b", "#e66767", "#f2b8b8"],
  status: { good: "#3ee6b4", warning: "#eda100", serious: "#eb6834", critical: "#ff5c72" },
  accent: "#3ee6b4",
  fontFamily: FONT,
  fontFamilyMono: FONT_MONO,
  fontSize: SIZES,
};

export const tokensFor = (mode: ThemeMode): ThemeTokens => (mode === "dark" ? DARK : LIGHT);
