/**
 * API Access Card
 *
 * There is no consumer API-key system in this build — PolicyEngine governs outbound
 * collection requests, not inbound API auth — so this card only ever links to the real,
 * unauthenticated surface: the generated OpenAPI docs and one real example request
 * against `BASE_URL`. Never show a fabricated key or an endpoint this API doesn't serve.
 */

import { useState } from "react";
import { BASE_URL, HEADLINE_SERIES } from "../api/client";
import { IconCode, IconCopy } from "./icons";

interface ApiAccessCardProps {
  onViewDocs?: () => void;
}

const SAMPLE_ENDPOINT = `GET ${BASE_URL}/v1/index?series=${HEADLINE_SERIES}&freq=M`;

export function ApiAccessCard({ onViewDocs }: ApiAccessCardProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard?.writeText(SAMPLE_ENDPOINT).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="flex h-full flex-col justify-between rounded-2xl border border-edge bg-surface p-5 shadow-card card-hover">
      {/* Top Header */}
      <div>
        <div className="flex items-start gap-2.5">
          <div className="mt-0.5 text-accent-ink">
            <IconCode width={18} height={18} />
          </div>
          <div>
            <h3 className="text-base font-bold text-ink">API Access</h3>
            <p className="text-xs text-ink-2">Integrate APIx data into your systems</p>
          </div>
        </div>

        <div className="mt-4">
          <a
            href={`${BASE_URL}/docs`}
            target="_blank"
            rel="noreferrer"
            onClick={onViewDocs}
            className="block w-full rounded-xl bg-accent px-3 py-2 text-center text-xs font-semibold text-navy shadow-sm transition-colors hover:brightness-110"
          >
            View API Documentation
          </a>
        </div>
      </div>

      {/* Code Snippet Box */}
      <div className="mt-4">
        <div className="flex items-center justify-between rounded-xl bg-navy px-3.5 py-3 text-ink shadow-inner">
          <div className="min-w-0 flex-1 font-mono text-[11px] leading-relaxed break-all">
            <span className="font-bold text-rose-400">GET </span>
            <span className="text-ink-2">
              {BASE_URL}/v1/index?series={HEADLINE_SERIES}&amp;freq=M
            </span>
          </div>
          <button
            type="button"
            onClick={handleCopy}
            className="ml-2 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-ink-2 hover:bg-white/10 hover:text-ink transition-colors"
            title="Copy API endpoint"
          >
            <IconCopy width={15} height={15} />
          </button>
        </div>
        {copied && (
          <p className="mt-1 text-right text-[10px] font-medium text-emerald-600">
            Copied endpoint to clipboard!
          </p>
        )}
      </div>
    </div>
  );
}
