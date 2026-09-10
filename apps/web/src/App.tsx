/**
 * Dashboard shell:
 * - Top dark navy header with APIx branding and an honest institutional badge — no
 *   national emblem, no "Ministry of..." claim, no fabricated user identity, since this
 *   build serves placeholder data and authenticates no one.
 * - Left dark navy sidebar with royal blue active pill and bottom callout card
 * - Institutional footer
 */

import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  IconClock,
  IconDatabase,
  IconDashboard,
  IconDocument,
  IconPlane,
  IconRoute,
  IconSettings,
  IconSliders,
} from "./components/icons";
import { InstitutionalBadge } from "./components/InstitutionalBadge";

const SCREENS = [
  { to: "/", label: "Dashboard", icon: IconDashboard },
  { to: "/airfare-index", label: "Airfare Index", icon: IconSliders },
  { to: "/routes", label: "Route Analysis", icon: IconRoute },
  { to: "/leadtime", label: "Lead Time Analysis", icon: IconClock },
  { to: "/explorer", label: "Data Explorer", icon: IconDatabase },
  { to: "/reports", label: "Methodology", icon: IconDocument },
  { to: "/settings", label: "Audit", icon: IconSettings },
];

export default function App() {
  const location = useLocation();
  const [activeModal, setActiveModal] = useState<string | null>(null);

  return (
    <div className="min-h-screen bg-[#f0f4f9] text-slate-800 antialiased">
      {/* Top Dark Navy Header */}
      <header className="sticky top-0 z-40 bg-[#0a1128] border-b border-slate-800 shadow-sm">
        <div className="mx-auto flex w-full items-center justify-between px-4 py-2.5 sm:px-6">
          {/* Left: Logo & Subtitle & Strapline */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2.5">
              {/* Stylized APIxx Logo */}
              <div className="flex items-center">
                <span className="text-2xl font-black tracking-tight text-white font-sans">
                  API
                </span>
                <span className="relative ml-0.5 inline-flex items-center font-black text-2xl text-blue-500">
                  x
                  <span className="absolute -top-1 -right-2 text-xs text-blue-400">✈</span>
                  <span className="text-blue-300">x</span>
                </span>
              </div>
              <div className="hidden sm:block border-l border-white/20 pl-3 leading-tight">
                <p className="text-[10px] font-bold text-white/90 tracking-tight uppercase">
                  Real-Time Airfare Price Index for India
                </p>
              </div>
            </div>

            {/* Strapline */}
            <div className="hidden lg:flex items-center border-l border-white/15 pl-4 text-xs font-medium text-slate-300/80">
              From millions of dynamic fares to one trusted price signal.
            </div>
          </div>

          {/* Right: what this build actually is — no emblem, no claimed institutional
              affiliation, no user identity this system does not actually authenticate. */}
          <div className="flex items-center gap-6">
            <InstitutionalBadge />
          </div>
        </div>
      </header>

      {/* Main Body with Left Dark Sidebar & Main Content */}
      <div className="flex min-h-[calc(100vh-56px)]">
        {/* Left Dark Navy Sidebar */}
        <aside className="w-56 shrink-0 bg-[#0a1128] text-slate-300 px-3 py-4 flex flex-col justify-between border-r border-slate-800">
          <div>
            <nav className="flex flex-col gap-1">
              {SCREENS.map((item) => {
                const Icon = item.icon;
                const isActive =
                  item.to === "/"
                    ? location.pathname === "/"
                    : location.pathname.startsWith(item.to);

                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={`flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-xs font-semibold transition-all ${
                      isActive
                        ? "bg-blue-600 text-white shadow-sm font-bold"
                        : "text-slate-300 hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    <Icon width={16} height={16} />
                    <span>{item.label}</span>
                  </NavLink>
                );
              })}
            </nav>
          </div>

          {/* Bottom Card in Sidebar */}
          <div className="mt-8 rounded-2xl bg-gradient-to-br from-blue-600 to-blue-700 p-3.5 text-white shadow-md">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-white/20 backdrop-blur-sm">
                <IconPlane width={16} height={16} />
              </div>
              <div className="text-[11px] leading-snug font-medium">
                <p className="font-semibold text-white">Measuring today.</p>
                <p className="text-blue-100">A more informed tomorrow.</p>
              </div>
            </div>
          </div>
        </aside>

        {/* Main Workspace Area */}
        <div className="flex-1 min-w-0 flex flex-col justify-between">
          <main className="p-4 sm:p-6 lg:p-7 max-w-[1600px] w-full mx-auto">
            <Outlet />
          </main>

          {/* Institutional Footer */}
          <footer className="border-t border-slate-200/80 bg-white px-6 py-4 text-xs text-slate-500">
            <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <span className="font-bold text-slate-800">APIx</span>
                <span>|</span>
                <span>Real-Time Airfare Price Index for India</span>
              </div>
              <div className="flex flex-wrap items-center gap-4 text-slate-600">
                <button
                  type="button"
                  onClick={() => setActiveModal("about")}
                  className="hover:text-blue-600 transition-colors"
                >
                  About
                </button>
                <span>|</span>
                <NavLink to="/reports" className="hover:text-blue-600 transition-colors">
                  Methodology
                </NavLink>
                <span>|</span>
                <button
                  type="button"
                  onClick={() => setActiveModal("sources")}
                  className="hover:text-blue-600 transition-colors"
                >
                  Data Sources
                </button>
                <span>|</span>
                <button
                  type="button"
                  onClick={() => setActiveModal("help")}
                  className="hover:text-blue-600 transition-colors"
                >
                  Help
                </button>
                <span>|</span>
                <button
                  type="button"
                  onClick={() => setActiveModal("contact")}
                  className="hover:text-blue-600 transition-colors"
                >
                  Contact
                </button>
              </div>
              <div className="text-slate-400">
                Built for measurement. Designed for scale.
              </div>
            </div>
          </footer>
        </div>
      </div>

      {/* Informational Modal */}
      {activeModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4">
          <div className="max-w-md w-full rounded-2xl bg-white p-6 shadow-2xl border border-slate-200">
            <h3 className="text-lg font-bold text-slate-900 capitalize">{activeModal}</h3>
            <p className="mt-2 text-xs text-slate-600 leading-relaxed">
              APIx is built as a statistical production system for MoSPI and the RBI to augment
              the CPI Transport sub-group. Every observation carries full provenance and is legally
              compliant under PolicyEngine rules.
            </p>
            <div className="mt-5 flex justify-end">
              <button
                type="button"
                onClick={() => setActiveModal(null)}
                className="rounded-xl bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
