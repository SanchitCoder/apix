/**
 * The header's institutional mark.
 *
 * Deliberately not the State Emblem of India or any "Ministry of..." wording: this
 * deployment serves EXAMPLE_ONLY / placeholder data (see the banner in App.tsx), so
 * anything implying an official Government of India publication here would be false.
 * What the badge claims instead is only what this build actually does — every quote
 * traceable, every request policy-gated — which is real, in `packages/apix_core`.
 */

import { IconAudit } from "./icons";

export function InstitutionalBadge() {
  return (
    <div className="hidden items-center gap-2.5 rounded-full border border-white/15 bg-white/10 py-1.5 pl-2.5 pr-3.5 backdrop-blur-sm sm:flex">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/15 text-on-navy">
        <IconAudit width={14} height={14} />
      </span>
      <div className="leading-tight">
        <p className="text-xs font-semibold text-on-navy">Statistical Index Program</p>
        <p className="text-[11px] text-on-navy-muted">Source-audited methodology</p>
      </div>
    </div>
  );
}
