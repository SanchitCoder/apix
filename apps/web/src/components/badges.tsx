/** Status badges. A placeholder must be visibly a placeholder on screen. */

const STATUS_STYLES: Record<string, string> = {
  EXAMPLE_ONLY: "bg-warning-soft text-warning-ink",
  PROVISIONAL: "bg-serious-soft text-serious-ink",
  PUBLISHED: "bg-good-soft text-good-ink",
  REVISED: "bg-accent-soft text-accent-ink",
};

const STATUS_LABELS: Record<string, string> = {
  EXAMPLE_ONLY: "Example data",
  PROVISIONAL: "Provisional",
  PUBLISHED: "Published",
  REVISED: "Revised",
};

export function DataStatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? "bg-raised text-ink-2";
  const label = STATUS_LABELS[status] ?? status;
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${style}`}
      title={
        status === "EXAMPLE_ONLY"
          ? "Contract placeholder values. These are not published statistics."
          : undefined
      }
    >
      {label}
    </span>
  );
}

export function SourceStatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    OK: "bg-good-soft text-good-ink",
    PARTIAL: "bg-warning-soft text-warning-ink",
    BLOCKED: "bg-critical-soft text-critical-ink",
    DISABLED: "bg-raised text-ink-2",
    ERROR: "bg-critical-soft text-critical-ink",
  };
  const icons: Record<string, string> = {
    OK: "✓",
    PARTIAL: "◐",
    BLOCKED: "⛔",
    DISABLED: "⏸",
    ERROR: "✗",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ${styles[status] ?? "bg-raised text-ink-2"}`}
    >
      <span aria-hidden="true">{icons[status] ?? "•"}</span>
      {status}
    </span>
  );
}
