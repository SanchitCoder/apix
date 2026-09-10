/**
 * Screen 6 — Audit and provenance.
 *
 * Click any point on the headline chart to drill down: index value -> the route indices
 * contributing to it -> the cleaned quotes behind a route -> one quote's full source,
 * timestamp, legal basis and payload hash. Plus the revision log and a vintage selector.
 *
 * This screen is principle 1 made interactive: every number a click away from the
 * evidence it rests on.
 */

import { useMemo, useState } from "react";
import { HEADLINE_SERIES } from "../api/client";
import {
  useContributors,
  useIndexSeries,
  useProvenance,
  useQuotes,
  useRevisions,
  useVintage,
} from "../api/hooks";
import { AuditArt } from "../components/illustrations";
import { ChartPanel } from "../components/ChartPanel";
import { DataStatusBadge } from "../components/badges";
import { EChart } from "../components/EChart";
import { PageHeader } from "../components/PageHeader";
import { formatDate, formatIndex, formatINR, formatPeriod, todayISO } from "../lib/format";
import { useTheme } from "../theme/ThemeContext";
import { baseOption, gridDefaults, timeAxis, tooltipDefaults, valueAxis } from "../theme/echartsTheme";

function Crumb({ label, active, onClick }: { label: string; active: boolean; onClick?: () => void }) {
  if (onClick === undefined) {
    return <span className={active ? "font-semibold text-ink" : "text-ink-2"}>{label}</span>;
  }
  return (
    <button type="button" onClick={onClick} className="font-medium text-accent-ink hover:underline">
      {label}
    </button>
  );
}

export default function Audit() {
  const { tokens } = useTheme();
  const headline = useIndexSeries(HEADLINE_SERIES);

  const [period, setPeriod] = useState<string | null>(null);
  const [route, setRoute] = useState<string | null>(null);
  const [quoteId, setQuoteId] = useState<string | null>(null);

  const contributors = useContributors(HEADLINE_SERIES, period ?? "2026-08-01");
  const quotes = useQuotes(route ?? "", period ?? "2026-08-01");
  const provenance = useProvenance(quoteId);
  const revisions = useRevisions();

  const [vintagePeriod, setVintagePeriod] = useState("2026-08-01");
  const [vintageAsOf, setVintageAsOf] = useState(todayISO());
  const vintage = useVintage(HEADLINE_SERIES, vintagePeriod, vintageAsOf);

  const option = useMemo(() => {
    if (headline.data === undefined) return null;
    const periods = headline.data.items.map((p) => formatPeriod(p.period));
    return {
      ...baseOption(tokens),
      grid: gridDefaults(),
      tooltip: tooltipDefaults(tokens),
      xAxis: { ...timeAxis(tokens), data: periods },
      yAxis: valueAxis(tokens, "Index"),
      series: [
        {
          name: "APIx headline",
          type: "line" as const,
          data: headline.data.items.map((p) => p.value),
          lineStyle: { width: 2, color: tokens.series[0] },
          itemStyle: { color: tokens.series[0] },
          symbolSize: 9,
          showSymbol: true,
        },
      ],
    };
  }, [headline.data, tokens]);

  const selectPeriod = (dataIndex: number) => {
    const point = headline.data?.items[dataIndex];
    if (point === undefined) return;
    setPeriod(point.period);
    setRoute(null);
    setQuoteId(null);
  };

  const nav =
    headline.data === undefined
      ? undefined
      : {
          seriesCount: 1,
          pointCount: () => headline.data.items.length,
          describe: (_s: number, d: number) => {
            const point = headline.data.items[d];
            return point === undefined
              ? ""
              : `${formatPeriod(point.period)}: index ${formatIndex(point.value)}. Press Enter to drill down.`;
          },
          onActivate: (_s: number, d: number) => selectPeriod(d),
        };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Audit & provenance"
        subtitle="Every number is a click away from the evidence it rests on: index value, contributing route indices, cleaned quotes, and each quote's source, timestamp and legal basis."
        art={<AuditArt />}
      />

      <ChartPanel
        title="APIx headline — click a point to audit it"
        isLoading={headline.isLoading}
        error={headline.error}
        dataStatus={headline.data?.meta.data_status}
      >
        {option !== null && (
          <EChart
            option={option}
            height={280}
            ariaLabel="APIx headline index over time. Activate a point to drill into its provenance."
            nav={nav}
            onPointClick={(_s, d) => selectPeriod(d)}
            testId="audit-index-chart"
          />
        )}
      </ChartPanel>

      {period !== null && (
        <section
          className="rounded-2xl border border-edge bg-surface p-5 shadow-card"
          aria-label="Provenance drill-down"
        >
          <nav aria-label="Drill-down path" className="mb-4 flex flex-wrap items-center gap-1 text-sm">
            <Crumb label={`${HEADLINE_SERIES} · ${formatPeriod(period)}`} active={route === null} onClick={route !== null ? () => { setRoute(null); setQuoteId(null); } : undefined} />
            {route !== null && (
              <>
                <span className="text-ink-2" aria-hidden="true">/</span>
                <Crumb label={route} active={quoteId === null} onClick={quoteId !== null ? () => setQuoteId(null) : undefined} />
              </>
            )}
            {quoteId !== null && (
              <>
                <span className="text-ink-2" aria-hidden="true">/</span>
                <Crumb label={`quote ${quoteId.slice(-6)}`} active />
              </>
            )}
          </nav>

          {route === null && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-ink">Contributing route indices</h3>
              {contributors.isLoading && <p className="text-sm text-ink-2">Loading…</p>}
              {contributors.error !== null && contributors.error !== undefined && (
                <p className="text-sm text-critical-ink">Could not load contributors.</p>
              )}
              {contributors.data !== undefined && (
                <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {contributors.data.items.map((c) => (
                    <li key={c.route_code}>
                      <button
                        type="button"
                        onClick={() => setRoute(c.route_code)}
                        className="w-full rounded-xl border border-edge px-3 py-2.5 text-left text-sm transition-colors hover:border-accent hover:bg-raised"
                      >
                        <span className="font-mono font-semibold text-ink">{c.route_code}</span>
                        <span className="ml-2 font-mono text-ink-2">index {formatIndex(c.index_value)}</span>
                        <span className="block text-xs text-ink-2">
                          {c.n_quotes.toLocaleString("en-IN")} quotes ·{" "}
                          {c.weight === null ? "unweighted (Phase 2 loads DGCA weights)" : `weight ${c.weight}`}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {route !== null && quoteId === null && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-ink">Cleaned quotes — {route}</h3>
              {quotes.isLoading && <p className="text-sm text-ink-2">Loading…</p>}
              {quotes.data !== undefined && (
                <div className="overflow-x-auto rounded-xl border border-edge">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-edge bg-raised text-ink-2">
                        <th className="px-3 py-2 font-semibold">Carrier</th>
                        <th className="px-3 py-2 font-semibold">Travel date</th>
                        <th className="px-3 py-2 font-semibold">Advance days</th>
                        <th className="px-3 py-2 font-semibold">Fare</th>
                        <th className="px-3 py-2 font-semibold">Treatment</th>
                        <th className="px-3 py-2 font-semibold" />
                      </tr>
                    </thead>
                    <tbody>
                      {quotes.data.items.map((q) => (
                        <tr key={q.quote_id} className="border-b border-grid last:border-0 even:bg-stripe">
                          <td className="px-3 py-2 font-mono">{q.carrier_iata}</td>
                          <td className="px-3 py-2 font-mono">{formatDate(q.travel_date)}</td>
                          <td className="px-3 py-2 font-mono">{q.advance_days}</td>
                          <td className="px-3 py-2 font-mono">{formatINR(q.total_fare)}</td>
                          <td className="px-3 py-2">
                            {q.is_outlier && (
                              <span className="rounded-full bg-critical-soft px-2 py-0.5 text-xs font-semibold text-critical-ink">
                                outlier ({q.outlier_rule})
                              </span>
                            )}
                            {q.is_imputed && (
                              <span className="rounded-full bg-warning-soft px-2 py-0.5 text-xs font-semibold text-warning-ink">
                                imputed ({q.imputation_method})
                              </span>
                            )}
                            {!q.is_outlier && !q.is_imputed && (
                              <span className="rounded-full bg-good-soft px-2 py-0.5 text-xs font-semibold text-good-ink">
                                clean
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <button
                              type="button"
                              onClick={() => setQuoteId(q.quote_id)}
                              className="font-medium text-accent-ink hover:underline"
                            >
                              Trace source
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {quoteId !== null && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-ink">Source and legal basis</h3>
              {provenance.isLoading && <p className="text-sm text-ink-2">Loading…</p>}
              {provenance.data !== undefined && (
                <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                  <div>
                    <dt className="text-ink-2">Source</dt>
                    <dd className="text-ink">{provenance.data.source.display_name}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-2">Legal basis</dt>
                    <dd className="text-ink">{provenance.data.source.legal_basis}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-2">Policy decision</dt>
                    <dd className="text-ink">{provenance.data.source.policy_decision}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-2">Collected at</dt>
                    <dd className="text-ink">{provenance.data.collected_at}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-2">Source URL hash</dt>
                    <dd className="mt-0.5 break-all rounded-lg bg-raised px-2 py-1 font-mono text-xs text-ink">
                      {provenance.data.source_url_hash}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ink-2">Content hash</dt>
                    <dd className="mt-0.5 break-all rounded-lg bg-raised px-2 py-1 font-mono text-xs text-ink">
                      {provenance.data.content_hash}
                    </dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="text-ink-2">Raw payload</dt>
                    <dd className="mt-0.5 break-all rounded-lg bg-raised px-2 py-1 font-mono text-xs text-ink">
                      {provenance.data.raw_payload_ref}
                    </dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="text-ink-2">Contributed to</dt>
                    <dd className="text-ink">{provenance.data.contributed_to.join(", ")}</dd>
                  </div>
                </dl>
              )}
            </div>
          )}
        </section>
      )}

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-edge bg-surface p-5 shadow-card">
          <h2 className="mb-3 text-base font-semibold text-ink">Vintage selector</h2>
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label htmlFor="vintage-period" className="block text-sm font-medium text-ink-2">
                Period
              </label>
              <input
                id="vintage-period"
                type="month"
                value={vintagePeriod.slice(0, 7)}
                onChange={(e) => setVintagePeriod(`${e.target.value}-01`)}
                className="mt-1.5 rounded-lg border border-edge bg-raised px-3 py-2 text-sm text-ink transition-colors focus:border-accent"
              />
            </div>
            <div>
              <label htmlFor="vintage-asof" className="block text-sm font-medium text-ink-2">
                As of
              </label>
              <input
                id="vintage-asof"
                type="date"
                value={vintageAsOf}
                onChange={(e) => setVintageAsOf(e.target.value)}
                className="mt-1.5 rounded-lg border border-edge bg-raised px-3 py-2 text-sm text-ink transition-colors focus:border-accent"
              />
            </div>
          </div>
          {vintage.data !== undefined && (
            <p className="mt-4 rounded-xl bg-raised px-3 py-2.5 text-sm text-ink">
              Value as of {formatDate(vintage.data.as_of)}:{" "}
              <strong className="font-mono">{formatIndex(vintage.data.value)}</strong>
              {vintage.data.revised_from !== null && vintage.data.revised_from !== undefined && (
                <span className="ml-2 text-ink-2">
                  (revised from {formatIndex(vintage.data.revised_from)})
                </span>
              )}
            </p>
          )}
        </div>

        <div className="rounded-2xl border border-edge bg-surface p-5 shadow-card">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-ink">Revision log</h2>
            {revisions.data !== undefined && <DataStatusBadge status={revisions.data.meta.data_status} />}
          </div>
          {revisions.isLoading && <p className="text-sm text-ink-2">Loading…</p>}
          {revisions.data !== undefined && (
            <ul className="flex flex-col gap-2 text-sm">
              {revisions.data.items.map((r, i) => (
                <li key={i} className="border-b border-grid pb-2 last:border-0">
                  <p className="font-mono text-ink">
                    {r.series} · {formatPeriod(r.period)}:{" "}
                    {r.old_value === null || r.old_value === undefined ? (
                      <span>first published at {formatIndex(r.new_value)}</span>
                    ) : (
                      <span>
                        {formatIndex(r.old_value)} → {formatIndex(r.new_value)}
                      </span>
                    )}
                  </p>
                  <p className="font-sans text-xs text-ink-2">
                    {formatDate(r.revised_at.slice(0, 10))} — {r.reason}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
