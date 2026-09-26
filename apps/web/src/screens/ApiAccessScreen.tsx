/**
 * Screen — API Access.
 *
 * There is no consumer API-key system in this build — PolicyEngine governs outbound
 * collection requests, not inbound API auth — so this screen never shows a fabricated
 * key. Endpoints listed here are the real routers mounted in `apps/api/src/apix_api/main.py`,
 * against the real `BASE_URL`.
 */

import { useState } from "react";
import { BASE_URL } from "../api/client";
import { IconCode, IconCopy } from "../components/icons";

export default function ApiAccessScreen() {
  const [copied, setCopied] = useState<string | null>(null);

  const copy = (key: string, text: string) => {
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(null), 2000);
    });
  };

  const ENDPOINTS = [
    {
      id: "index",
      method: "GET",
      path: "/v1/index?series=APIX.ALL.M&freq=M",
      desc: "Fetch a published index series with vintage dates and coverage metadata.",
    },
    {
      id: "routes",
      method: "GET",
      path: "/v1/routes",
      desc: "List the current route basket.",
    },
    {
      id: "leadtime",
      method: "GET",
      path: "/v1/leadtime/{code}",
      desc: "Mean fare by advance-purchase window for one route.",
    },
    {
      id: "heatmap",
      method: "GET",
      path: "/v1/heatmap",
      desc: "The route x period index grid the dashboard renders as a heatmap.",
    },
    {
      id: "coverage",
      method: "GET",
      path: "/v1/coverage?date=2026-09-07",
      desc: "What was actually collected on a date, including what was not.",
    },
    {
      id: "quotes",
      method: "GET",
      path: "/v1/quotes?route=DEL-BOM&period=2026-08-01",
      desc: "Cleaned observations behind a route and period.",
    },
    {
      id: "provenance",
      method: "GET",
      path: "/v1/provenance/{quote_id}",
      desc: "Trace any published number down to its source, timestamp, and legal basis.",
    },
    {
      id: "export",
      method: "GET",
      path: "/v1/export.csv?series=APIX.ALL.M",
      desc: "Flat CSV download of a published index series.",
    },
    {
      id: "sdmx",
      method: "GET",
      path: "/v1/sdmx/data/{flow_ref}/{key}",
      desc: "SDMX-JSON 2.0 statistical data message for central banks and MoSPI.",
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="rounded-2xl border border-edge bg-surface p-6 shadow-card flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-accent-ink">
            <IconCode width={20} height={20} />
            <span className="text-xs font-bold uppercase tracking-wider">Developer &amp; Consumer Integration</span>
          </div>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-ink">
            APIx Programmatic Access &amp; SDMX Feeds
          </h2>
          <p className="mt-1 text-xs text-ink-2 max-w-2xl">
            Integrate national airfare statistics into external macroeconomic forecasting, CPI modeling,
            and research pipelines via OpenAPI 3.1 and SDMX-JSON 2.0 protocols. No API key is required —
            the API is unauthenticated in this build.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <a
            href={`${BASE_URL}/docs`}
            target="_blank"
            rel="noreferrer"
            className="rounded-xl bg-accent px-5 py-2.5 text-xs font-bold text-navy shadow-sm hover:brightness-110 transition-colors"
          >
            Interactive Swagger Docs ↗
          </a>
        </div>
      </div>

      {/* Endpoints List */}
      <div className="flex flex-col gap-4">
        {ENDPOINTS.map((ep) => (
          <div
            key={ep.id}
            className="rounded-2xl border border-edge bg-surface p-5 shadow-card flex flex-col gap-2.5"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-ink-2">{ep.desc}</span>
              <button
                type="button"
                onClick={() => copy(ep.id, `${BASE_URL}${ep.path}`)}
                className="flex items-center gap-1 text-xs text-accent-ink hover:underline"
              >
                <IconCopy width={13} height={13} />
                {copied === ep.id ? "Copied" : "Copy URL"}
              </button>
            </div>
            <div className="flex items-center justify-between rounded-xl bg-navy px-4 py-3 font-mono text-xs text-ink shadow-inner">
              <div>
                <span className="font-bold text-rose-400 mr-2">{ep.method}</span>
                <span className="text-ink-2">{BASE_URL}{ep.path}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
