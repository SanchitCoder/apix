/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Semantic colours only — the values live in index.css / src/theme/tokens.ts.
      colors: {
        page: "var(--page)",
        surface: "var(--surface)",
        raised: "var(--surface-raised)",
        ink: "var(--ink)",
        "ink-2": "var(--ink-secondary)",
        muted: "var(--ink-muted)",
        grid: "var(--grid)",
        axis: "var(--axis)",
        edge: "var(--border)",
        accent: "var(--accent)",
        "accent-ink": "var(--accent-ink)",
        "good-ink": "var(--status-good-ink)",
        "warning-ink": "var(--status-warning-ink)",
        "serious-ink": "var(--status-serious-ink)",
        "critical-ink": "var(--status-critical-ink)",
        "accent-soft": "var(--accent-soft)",
        "good-soft": "var(--good-soft)",
        "warning-soft": "var(--warning-soft)",
        "serious-soft": "var(--serious-soft)",
        "critical-soft": "var(--critical-soft)",
        stripe: "var(--table-stripe)",
        navy: "var(--navy)",
        "navy-2": "var(--navy-2)",
        "on-navy": "var(--on-navy)",
        "on-navy-muted": "var(--on-navy-muted)",
        sidebar: "var(--sidebar-bg)",
        "sidebar-active": "var(--sidebar-active-bg)",
        "sidebar-active-ink": "var(--sidebar-active-ink)",
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "-apple-system", '"Segoe UI"', "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "var(--shadow-card)",
        "card-hover": "var(--shadow-card-hover)",
      },
    },
  },
  plugins: [],
};
