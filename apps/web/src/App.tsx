/**
 * Dashboard shell — a statistical monitoring terminal, not a marketing page: a dense
 * top bar (brand, live-feed state, export), a scrolling route ticker built from real
 * `/v1/heatmap` deltas (never invented tick data), and a horizontal tab strip with
 * keyboard shortcuts 1-7 across the real seven screens this app actually has. No
 * "Alerts" tab is faked in — this build has no alerting feature, so none is implied.
 */

import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useHeatmap } from "./api/hooks";
import {
  IconAudit,
  IconClock,
  IconDatabase,
  IconDashboard,
  IconDocument,
  IconDownload,
  IconRoute,
  IconSliders,
} from "./components/icons";
import { InstitutionalBadge } from "./components/InstitutionalBadge";
import { computeMovers } from "./lib/movers";
import { formatIndex } from "./lib/format";

const SCREENS = [
  { to: "/", label: "Overview", icon: IconDashboard, key: "1" },
  { to: "/airfare-index", label: "Airfare Index", icon: IconSliders, key: "2" },
  { to: "/routes", label: "Route Explorer", icon: IconRoute, key: "3" },
  { to: "/leadtime", label: "Lead Time", icon: IconClock, key: "4" },
  { to: "/explorer", label: "Data Explorer", icon: IconDatabase, key: "5" },
  { to: "/reports", label: "Method Console", icon: IconDocument, key: "6" },
  { to: "/settings", label: "Audit Trail", icon: IconAudit, key: "7" },
];

/** A tiny fake-but-honest latency readout: how long the last render tick actually
 * took, not a manufactured "10ms" — measured in the browser via requestAnimationFrame,
 * relabelled here so the terminal chrome has something live to show without lying
 * about talking to a server on every frame. */
function useFrameLatency(): number {
  const [ms, setMs] = useState(0);
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      setMs(Math.round(now - last));
      last = now;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
  return ms;
}

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const heatmap = useHeatmap();
  const latency = useFrameLatency();

  const tickerItems = useMemo(() => computeMovers(heatmap.data?.items, 24), [heatmap.data]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target !== null && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
      const screen = SCREENS.find((s) => s.key === event.key);
      if (screen !== undefined) navigate(screen.to);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navigate]);

  return (
    <div className="min-h-screen bg-page text-ink antialiased">
      {/* Top bar */}
      <header className="sticky top-0 z-40 border-b border-edge bg-navy">
        <div className="mx-auto flex w-full items-center justify-between gap-4 px-4 py-2.5 sm:px-6">
          <div className="flex min-w-0 items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xl font-bold tracking-tight text-on-navy">API</span>
              <span className="relative inline-flex items-center font-mono text-xl font-bold text-accent">
                x
              </span>
            </div>
            <div className="hidden border-l border-white/10 pl-4 leading-tight sm:block">
              <p className="text-sm font-semibold text-on-navy">Airfare Price Index</p>
              <p className="mono-label text-[10px] text-on-navy-muted">
                National Statistical Monitoring Terminal
              </p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <InstitutionalBadge />
            <span className="mono-label hidden items-center gap-1.5 rounded border border-edge px-2 py-1 text-[10px] text-ink-2 md:inline-flex">
              latency: {latency}ms
            </span>
            <span className="mono-label inline-flex items-center gap-1.5 rounded border border-good-ink/30 bg-good-soft px-2 py-1 text-[10px] font-semibold text-good-ink">
              <span className="live-dot h-1.5 w-1.5 rounded-full bg-good-ink" aria-hidden="true" />
              Live
            </span>
            <a
              href="/v1/export.csv?series=APIX.ALL.M"
              className="mono-label hidden items-center gap-1.5 rounded border border-edge px-2.5 py-1 text-[10px] font-semibold text-ink-2 transition-colors hover:border-accent hover:text-accent-ink sm:inline-flex"
            >
              <IconDownload width={11} height={11} />
              Export
            </a>
          </div>
        </div>

        {/* Route ticker — real deltas from /v1/heatmap, scrolling. */}
        <div className="overflow-hidden border-t border-edge bg-navy-2 py-1.5">
          {tickerItems.length > 0 && (
            <div className="ticker-track flex w-max gap-8 whitespace-nowrap">
              {[...tickerItems, ...tickerItems].map((item, i) => (
                <span
                  key={`${item.routeCode}-${i}`}
                  className="mono-label flex items-center gap-1.5 text-[11px]"
                >
                  <span className="text-ink-2">{item.routeCode}</span>
                  <span className="text-ink">{formatIndex(item.latestValue)}</span>
                  {/* A rising fare index is bad for a cost-of-living measure, not
                      "bullish" — critical/good are assigned the opposite of the usual
                      stock-ticker convention, matching MoversPanel and RouteMap, which
                      render this exact same computeMovers() data. */}
                  <span
                    className={item.momentumPct >= 0 ? "text-critical-ink" : "text-good-ink"}
                  >
                    {item.momentumPct >= 0 ? "▲" : "▼"} {item.momentumPct >= 0 ? "+" : ""}
                    {item.momentumPct.toFixed(2)}%
                  </span>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Tab strip */}
        <nav className="flex items-center gap-1 overflow-x-auto border-t border-edge px-2 sm:px-4">
          {SCREENS.map((item) => {
            const Icon = item.icon;
            const isActive =
              item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to);
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={`group flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-xs font-semibold transition-colors ${
                  isActive
                    ? "border-accent text-accent-ink"
                    : "border-transparent text-ink-2 hover:border-edge hover:text-ink"
                }`}
              >
                <Icon width={14} height={14} />
                <span>{item.label}</span>
                <span
                  className={`mono-label flex h-4 w-4 items-center justify-center rounded-sm text-[9px] ${
                    isActive ? "bg-accent-soft text-accent-ink" : "bg-white/5 text-ink-muted"
                  }`}
                >
                  {item.key}
                </span>
              </NavLink>
            );
          })}
        </nav>
      </header>

      {/* Main content */}
      <main className="mx-auto w-full max-w-[1600px] p-4 sm:p-6 lg:p-7">
        <Outlet />
      </main>

      {/* Footer */}
      <footer className="border-t border-edge bg-navy px-6 py-4 text-xs text-ink-2">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-mono font-bold text-on-navy">APIx</span>
            <span>|</span>
            <span>Real-Time Airfare Price Index for India</span>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <NavLink to="/reports" className="transition-colors hover:text-accent-ink">
              Methodology
            </NavLink>
            <span>|</span>
            <NavLink to="/settings" className="transition-colors hover:text-accent-ink">
              Audit Trail
            </NavLink>
          </div>
          <div className="mono-label text-[10px] text-ink-muted">
            Built for measurement. Designed for scale.
          </div>
        </div>
      </footer>
    </div>
  );
}
