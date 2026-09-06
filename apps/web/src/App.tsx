/**
 * Dashboard shell: navy institutional header, screen sidebar, and the data-status
 * banner.
 *
 * The banner reads the headline series' meta and stays visible on every screen while
 * the API serves anything other than published statistics — a placeholder must be
 * visibly a placeholder on screen, not only in the JSON.
 */

import { NavLink, Outlet } from "react-router-dom";
import { HEADLINE_SERIES } from "./api/client";
import { useIndexSeries } from "./api/hooks";
import {
  IconAudit,
  IconDashboard,
  IconHeatmap,
  IconLeadTime,
  IconMethod,
  IconPlane,
  IconRoute,
} from "./components/icons";
import { useTheme } from "./theme/ThemeContext";

const SCREENS = [
  { to: "/", label: "Dashboard", icon: IconDashboard },
  { to: "/routes", label: "Route explorer", icon: IconRoute },
  { to: "/heatmap", label: "Sector heatmap", icon: IconHeatmap },
  { to: "/leadtime", label: "Lead-time curve", icon: IconLeadTime },
  { to: "/method", label: "Method console", icon: IconMethod },
  { to: "/audit", label: "Audit & provenance", icon: IconAudit },
];

function ThemeToggle() {
  const { preference, setPreference } = useTheme();
  return (
    <div>
      <label htmlFor="theme-select" className="visually-hidden">
        Colour theme
      </label>
      <select
        id="theme-select"
        value={preference}
        onChange={(event) =>
          setPreference(event.target.value as "light" | "dark" | "system")
        }
        className="rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-sm text-on-navy backdrop-blur-sm transition-colors hover:bg-white/15"
      >
        <option className="text-ink" value="system">
          System theme
        </option>
        <option className="text-ink" value="light">
          Light theme
        </option>
        <option className="text-ink" value="dark">
          Dark theme
        </option>
      </select>
    </div>
  );
}

export default function App() {
  const headline = useIndexSeries(HEADLINE_SERIES);
  const dataStatus = headline.data?.meta.data_status;

  return (
    <div className="min-h-screen bg-page">
      <a
        href="#main"
        className="visually-hidden focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-raised focus:px-3 focus:py-2"
      >
        Skip to content
      </a>

      <header
        className="sticky top-0 z-40 border-b border-black/10"
        style={{ background: "linear-gradient(120deg, var(--navy), var(--navy-2))" }}
      >
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-on-navy shadow-sm">
              <IconPlane width={20} height={20} />
            </span>
            <div className="leading-tight">
              <p className="text-lg font-semibold tracking-tight text-on-navy">APIx</p>
              <p className="text-xs text-on-navy-muted">Real-time airfare price index for India</p>
            </div>
          </div>
          <ThemeToggle />
        </div>
      </header>

      {dataStatus !== undefined && dataStatus !== "PUBLISHED" && (
        <div className="border-b border-warning-ink/30 bg-warning-ink/10" role="status">
          <p className="mx-auto flex max-w-[1400px] items-center gap-2 px-4 py-2 text-sm text-warning-ink sm:px-6">
            <span aria-hidden="true">⚠</span>
            <strong>Data status: {dataStatus}.</strong>{" "}
            {dataStatus === "EXAMPLE_ONLY"
              ? "This deployment serves contract placeholders — nothing shown here is a published statistic."
              : "These numbers are not final published statistics."}
          </p>
        </div>
      )}

      <div className="mx-auto flex max-w-[1400px] items-start gap-0 lg:gap-6 lg:px-6">
        <nav
          aria-label="Screens"
          className="sticky top-[65px] z-30 flex w-full gap-1 overflow-x-auto border-b border-edge bg-sidebar px-3 py-2 lg:top-[65px] lg:w-60 lg:shrink-0 lg:flex-col lg:overflow-visible lg:border-b-0 lg:border-r lg:px-3 lg:py-5"
        >
          <ul className="flex w-full gap-1 lg:flex-col">
            {SCREENS.map((screen) => {
              const Icon = screen.icon;
              return (
                <li key={screen.to} className="shrink-0">
                  <NavLink
                    to={screen.to}
                    end={screen.to === "/"}
                    className={({ isActive }) =>
                      `flex items-center gap-2.5 whitespace-nowrap rounded-xl px-3 py-2.5 text-sm transition-colors ${
                        isActive
                          ? "bg-sidebar-active font-semibold text-sidebar-active-ink"
                          : "text-ink-2 hover:bg-raised hover:text-ink"
                      }`
                    }
                  >
                    <Icon />
                    {screen.label}
                  </NavLink>
                </li>
              );
            })}
          </ul>
        </nav>

        <main id="main" className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-0">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
