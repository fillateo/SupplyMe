"use client";

import { useEffect, useRef } from "react";

import type { Evidence } from "@/lib/types";
import { ConfidenceMeter } from "./primitives";

const SOURCE_LABEL: Record<string, string> = {
  official_website: "Official Supplier Website",
  brand_website: "Client Brand Website",
  maps_listing: "Google Maps Verified Location",
  directory: "Trade Directory / B2B Registry",
  news: "News & Press Report",
  industry_publication: "Industry Trade Publication",
  search_result: "Search Engine Index Snippet",
  supplier_email: "Direct Supplier Email Correspondence",
  unknown: "External Source",
};

const SOURCE_CAVEAT: Record<string, string> = {
  maps_listing:
    "Proves physical entity existence and location footprint. Public reviews do not guarantee production tolerance or batch SLA.",
  official_website:
    "Supplier's self-published marketing claim. Cross-referenced against public directories.",
  search_result:
    "Search result snippet only — full document content not yet scraped.",
  supplier_email:
    "Direct written representation received in the mission mailbox.",
};

const STRENGTH_TONE: Record<string, { label: string; tone: string }> = {
  strong: {
    label: "High Evidence",
    tone: "bg-emerald-50 text-emerald-700 border-emerald-200",
  },
  moderate: {
    label: "Moderate Evidence",
    tone: "bg-blue-50 text-blue-700 border-blue-200",
  },
  weak: {
    label: "Weak Evidence",
    tone: "bg-amber-50 text-amber-700 border-amber-200",
  },
  none: {
    label: "No Backing Citation",
    tone: "bg-rose-50 text-rose-700 border-rose-200",
  },
};

export function EvidenceDrawer({
  open,
  title,
  records,
  onClose,
}: {
  open: boolean;
  title: string;
  records: Evidence[];
  onClose: () => void;
}) {
  const panel = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    panel.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      {/* Soft light backdrop */}
      <button
        className="absolute inset-0 cursor-default bg-slate-900/30 backdrop-blur-xs transition-opacity"
        onClick={onClose}
        aria-label="Close evidence inspector"
      />

      <aside
        ref={panel}
        tabIndex={-1}
        className="relative flex h-full w-full max-w-xl animate-drawer-in flex-col bg-white border-l border-slate-200 shadow-2xl outline-none"
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 bg-slate-50/90 px-6 py-5">
          <div className="min-w-0">
            <span className="text-xs font-semibold uppercase tracking-wider text-blue-600">
              Source Evidence Audit
            </span>
            <h2 className="mt-1 truncate text-lg font-bold text-slate-900">{title}</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              {records.length} citation {records.length === 1 ? "record" : "records"} on file
            </p>
          </div>
          <button
            id="close-evidence-drawer"
            onClick={onClose}
            aria-label="Close evidence audit"
            className="btn btn-quiet px-3 py-1.5 text-xs hover:bg-slate-100"
          >
            Close ✕
          </button>
        </header>

        <div className="scroll-thin flex-1 space-y-4 overflow-y-auto p-6">
          {records.length === 0 && (
            <div className="rounded-lg border border-dashed border-slate-200 p-8 text-center bg-slate-50">
              <p className="text-sm font-medium text-slate-700">No citations recorded</p>
              <p className="mt-1 text-xs text-slate-500">
                This figure is unestablished or estimated by the model without direct citation.
              </p>
            </div>
          )}

          {records.map((record) => {
            const strength = STRENGTH_TONE[record.evidence_strength] ?? STRENGTH_TONE.moderate;
            return (
              <article
                key={record.id}
                className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-subtle"
              >
                <div className="flex items-start justify-between gap-3 border-b border-slate-100 bg-slate-50/60 px-4 py-3">
                  <p className="text-xs font-semibold text-slate-800 leading-snug">
                    {record.claim}
                  </p>
                  <span
                    className={`shrink-0 rounded px-2 py-0.5 text-xs font-semibold border ${strength.tone}`}
                  >
                    {strength.label}
                  </span>
                </div>

                {record.evidence_excerpt && (
                  <blockquote className="border-l-2 border-blue-500 bg-blue-50/50 px-4 py-2.5 my-3 mx-4 rounded-r text-xs italic leading-relaxed text-slate-800 font-mono">
                    “{record.evidence_excerpt}”
                  </blockquote>
                )}

                <dl className="space-y-2 px-4 py-3 text-xs">
                  <Row label="Source Entity">
                    <span className="font-medium text-slate-800">
                      {SOURCE_LABEL[record.source_type] ?? record.source_type}
                      {record.source_title && (
                        <span className="text-slate-500"> — {record.source_title}</span>
                      )}
                    </span>
                  </Row>

                  {record.source_url && (
                    <Row label="Resource URL">
                      <a
                        href={record.source_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="break-all font-mono text-xs text-blue-600 underline hover:text-blue-800"
                      >
                        {record.source_url}
                      </a>
                    </Row>
                  )}

                  <Row label="Retrieved At">
                    <span className="font-mono text-slate-600">{formatTimestamp(record.retrieved_at)}</span>
                  </Row>

                  <Row label="Confidence">
                    <div className="flex items-center gap-2">
                      <ConfidenceMeter value={record.confidence} tone="blue" />
                      <span className="font-mono text-xs font-semibold text-slate-800">
                        {Math.round(record.confidence * 100)}%
                      </span>
                    </div>
                  </Row>
                </dl>

                {SOURCE_CAVEAT[record.source_type] && (
                  <p className="border-t border-slate-100 bg-slate-50 px-4 py-2.5 text-xs leading-relaxed text-slate-500">
                    <span className="font-semibold text-slate-700">Methodology Note: </span>
                    {SOURCE_CAVEAT[record.source_type]}
                  </p>
                )}
              </article>
            );
          })}
        </div>
      </aside>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 items-baseline">
      <dt className="w-24 shrink-0 text-xs font-medium text-slate-500">{label}</dt>
      <dd className="min-w-0 flex-1">{children}</dd>
    </div>
  );
}

export function formatTimestamp(value: string | number): string {
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toISOString().replace("T", " ").slice(0, 19) + " UTC";
}

export function formatClock(value: string | number): string {
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toISOString().slice(11, 19);
}


