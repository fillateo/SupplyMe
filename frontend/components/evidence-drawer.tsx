"use client";

import { useEffect } from "react";

import type { Evidence } from "@/lib/types";
import { ConfidenceMeter } from "./primitives";

const SOURCE_LABEL: Record<string, string> = {
  official_website: "the supplier's own website",
  brand_website: "the brand's own website",
  maps_listing: "a Google Maps listing",
  directory: "a business directory",
  news: "a news report",
  industry_publication: "an industry publication",
  youtube: "a YouTube video",
  search_result: "a search result",
  supplier_email: "an email from the supplier",
  supplier_call: "a recorded call with the supplier",
  unknown: "an unidentified source",
};

/**
 * What a source can and cannot establish. Spelled out because the distinction
 * is the product: a Maps listing proves a business exists at an address, and a
 * factory-tour video proves a factory exists. Neither says anything about who
 * that factory's customers are, and the interface should not let a reader
 * quietly assume otherwise.
 */
const SOURCE_CAVEAT: Record<string, string> = {
  maps_listing:
    "Establishes the business exists at this location. Reviews are not evidence of production quality.",
  youtube:
    "Establishes what was filmed. Not evidence of who the supplier's customers are.",
  official_website: "The supplier describing itself. Not independent confirmation.",
  search_result: "A snippet only — the page itself was not read.",
  supplier_email: "Stated to us directly, and binding in the way an email is.",
  supplier_call: "Stated to us on a call. The transcript is on the vendor record.",
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
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true">
      <button
        className="absolute inset-0 cursor-default bg-ink/20"
        onClick={onClose}
        aria-label="Close sources"
      />
      <aside className="relative flex h-full w-full max-w-xl animate-drawer-in flex-col bg-surface shadow-drawer">
        <header className="flex items-start justify-between gap-4 border-b border-rule px-6 py-4">
          <div className="min-w-0">
            <p className="col-label">Where this came from</p>
            <h2 className="mt-1 truncate font-mono text-lg text-ink">{title}</h2>
            <p className="mt-0.5 text-xs text-muted">
              {records.length} {records.length === 1 ? "source" : "sources"} on file
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-sm px-2 py-1 font-mono text-2xs uppercase tracking-[0.08em]
                       text-muted hover:bg-paper hover:text-ink"
          >
            Close
          </button>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
          {records.length === 0 && (
            <p className="text-sm text-muted">
              No source is recorded for this figure. It should not be relied on.
            </p>
          )}
          {records.map((record) => (
            <article key={record.id} className="rounded-md border border-rule">
              <div className="flex items-baseline justify-between gap-3 border-b border-rule px-4 py-2.5">
                <p className="text-sm text-ink">{record.claim}</p>
                <span className="col-label shrink-0">{record.evidence_strength}</span>
              </div>

              <blockquote className="border-l-2 border-petrol bg-paper/60 px-4 py-3">
                <p className="font-serif text-sm italic leading-relaxed text-ink">
                  &ldquo;{record.evidence_excerpt}&rdquo;
                </p>
              </blockquote>

              <dl className="space-y-2 px-4 py-3 text-xs">
                <Row label="Source">
                  <span className="text-ink">
                    {SOURCE_LABEL[record.source_type] ?? record.source_type}
                  </span>
                </Row>
                {record.source_url && (
                  <Row label="URL">
                    <a
                      href={record.source_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="break-all font-mono text-petrol underline decoration-dotted underline-offset-4"
                    >
                      {record.source_url}
                    </a>
                  </Row>
                )}
                <Row label="Retrieved">
                  <span className="figure">{formatTimestamp(record.retrieved_at)}</span>
                </Row>
                <Row label="Confidence">
                  <span className="flex items-center gap-2">
                    <ConfidenceMeter value={record.confidence} />
                    <span className="figure">{Math.round(record.confidence * 100)}%</span>
                  </span>
                </Row>
              </dl>

              {SOURCE_CAVEAT[record.source_type] && (
                <p className="border-t border-rule px-4 py-2.5 text-xs text-muted">
                  {SOURCE_CAVEAT[record.source_type]}
                </p>
              )}
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="col-label w-20 shrink-0 pt-0.5">{label}</dt>
      <dd className="min-w-0 flex-1">{children}</dd>
    </div>
  );
}

export function formatTimestamp(value: string | number): string {
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toISOString().replace("T", " ").slice(0, 19);
}
