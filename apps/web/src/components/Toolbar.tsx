/**
 * Dashboard filter bar: which route the mini route-analysis and lead-time panels focus
 * on, which coverage date the stat tiles report, and which carrier narrows the lead-time
 * bars. A route text field would invite codes the API doesn't serve — it's a select over
 * the real basket, styled as a search field.
 *
 * Selections are staged locally and only take effect on "Apply", so picking through
 * routes doesn't fire a refetch per keystroke.
 */

import { useState } from "react";
import type { CarrierOut, RouteSummary } from "../api/client";
import { IconCalendar } from "./icons";

export interface ToolbarValue {
  route: string;
  date: string;
  carrier: string;
}

interface ToolbarProps {
  routes: RouteSummary[];
  carriers: CarrierOut[];
  value: ToolbarValue;
  onApply: (value: ToolbarValue) => void;
}

export function Toolbar({ routes, carriers, value, onApply }: ToolbarProps) {
  const [pending, setPending] = useState(value);
  const dirty = pending.route !== value.route || pending.date !== value.date || pending.carrier !== value.carrier;

  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-2xl border border-edge bg-surface p-4 shadow-card"
      onSubmit={(e) => {
        e.preventDefault();
        onApply(pending);
      }}
    >
      <div className="min-w-[160px] flex-1">
        <label htmlFor="tb-route" className="block text-xs font-medium text-ink-2">
          Route
        </label>
        <select
          id="tb-route"
          value={pending.route}
          onChange={(e) => setPending({ ...pending, route: e.target.value })}
          className="mt-1 w-full rounded-lg border border-edge bg-raised px-3 py-2 text-sm text-ink transition-colors focus:border-accent"
        >
          {routes.map((r) => (
            <option key={r.code} value={r.code}>
              {r.code}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="tb-date" className="block text-xs font-medium text-ink-2">
          Coverage date
        </label>
        <div className="relative mt-1">
          <IconCalendar
            width={14}
            height={14}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-2"
          />
          <input
            id="tb-date"
            type="date"
            value={pending.date}
            onChange={(e) => setPending({ ...pending, date: e.target.value })}
            className="rounded-lg border border-edge bg-raised py-2 pl-8 pr-3 text-sm text-ink transition-colors focus:border-accent"
          />
        </div>
      </div>

      <div className="min-w-[140px]">
        <label htmlFor="tb-carrier" className="block text-xs font-medium text-ink-2">
          Carrier
        </label>
        <select
          id="tb-carrier"
          value={pending.carrier}
          onChange={(e) => setPending({ ...pending, carrier: e.target.value })}
          className="mt-1 w-full rounded-lg border border-edge bg-raised px-3 py-2 text-sm text-ink transition-colors focus:border-accent"
        >
          <option value="">All carriers</option>
          {carriers.map((c) => (
            <option key={c.iata} value={c.iata}>
              {c.name} ({c.iata})
            </option>
          ))}
        </select>
      </div>

      <button
        type="submit"
        disabled={!dirty}
        className="rounded-full bg-accent px-5 py-2 text-sm font-semibold text-navy transition-colors hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Apply
      </button>
    </form>
  );
}
