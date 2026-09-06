/** A single headline number. The number is the chart — no chart chrome around it. */

import type { ReactNode } from "react";
import { formatPct } from "../lib/format";
import { revealStyle } from "../lib/revealStyle";
import { useCountUpText } from "../lib/useCountUp";

interface StatTileProps {
  label: string;
  value: string;
  delta?: { pct: number | null; unavailableReason?: string };
  icon?: ReactNode;
  /** Stagger position within its grid — drives the reveal-on-mount delay only. */
  index?: number;
}

export function StatTile({ label, value, delta, icon, index = 0 }: StatTileProps) {
  const displayValue = useCountUpText(value);

  return (
    <div
      className="reveal card-hover flex flex-col gap-3 rounded-2xl border border-edge bg-surface p-5 shadow-card"
      style={revealStyle(index)}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-ink-2">{label}</p>
        {icon !== undefined && (
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-ink">
            {icon}
          </span>
        )}
      </div>
      <p className="font-mono text-3xl font-semibold tabular-nums text-ink">{displayValue}</p>
      {delta !== undefined && (
        <p className="text-sm">
          {delta.pct === null ? (
            <span className="text-ink-2">{delta.unavailableReason ?? "not available"}</span>
          ) : (
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${
                delta.pct >= 0 ? "bg-good-soft text-good-ink" : "bg-critical-soft text-critical-ink"
              }`}
            >
              <span aria-hidden="true">{delta.pct >= 0 ? "▲" : "▼"}</span>
              {formatPct(delta.pct)}
            </span>
          )}
        </p>
      )}
    </div>
  );
}
