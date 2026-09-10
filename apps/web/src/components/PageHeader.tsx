/**
 * The single H2 landing point for each screen. Every screen was previously missing a
 * heading of its own — the sidebar link was the only place its name appeared — which
 * both a screen reader user landing on a route and a sighted user scanning the page
 * lacked. The emblem on the right is one of `illustrations.tsx`: a miniature of the
 * screen's own chart grammar, not stock art.
 */

import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  subtitle: string;
  art: ReactNode;
}

export function PageHeader({ title, subtitle, art }: PageHeaderProps) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-2xl border border-edge bg-surface p-5 shadow-card">
      <div className="min-w-0">
        <h2 className="text-xl font-semibold tracking-tight text-ink">{title}</h2>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">{subtitle}</p>
      </div>
      <div className="hidden shrink-0 sm:block">{art}</div>
    </div>
  );
}
