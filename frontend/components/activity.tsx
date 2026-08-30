"use client";

import type { ActivityEntry } from "@/lib/types";
import { formatTimestamp } from "./evidence-drawer";

/*
 * Every row here is a stored workflow event read back from the database. There
 * is no synthesised progress and no "thinking" animation: if a line is on
 * screen, that step actually ran and is in the event log.
 */

const EVENT_COPY: Record<string, string> = {
  "mission.created": "Mission opened",
  "requirements.created": "Objective read",
  "supply_chain.planned": "Supply chain decomposed",
  "vendor.discovery.started": "Searching for suppliers",
  "vendor.discovered": "Supplier found",
  "vendor.research.started": "Researching supplier",
  "evidence.found": "Evidence recorded",
  "brand.claim.found": "Brand claim to check",
  "brand.claim.adjudicated": "Brand claim judged",
  "vendor.qualified": "Supplier qualified",
  "vendor.rejected": "Supplier ruled out",
  "vendor.contact.required": "Decided to make contact",
  "email.draft.created": "Email drafted",
  "approval.requested": "Waiting for your approval",
  "approval.granted": "You approved it",
  "approval.denied": "You declined it",
  "email.sent": "Email sent",
  "email.received": "Supplier replied",
  "quote.extracted": "Quotation read",
  "conflict.detected": "Sources disagree",
  "followup.required": "Following up",
  "vendor.updated": "Supplier record updated",
  "recommendation.ready": "Ranking computed",
  "mission.completed": "Mission finished",
  "mission.failed": "Mission stopped",
};

const NOTABLE = new Set([
  "conflict.detected", "email.received",
  "brand.claim.adjudicated", "mission.completed", "recommendation.ready",
]);

export function ActivityFeed({
  entries,
  vendorNames,
  limit,
}: {
  entries: ActivityEntry[];
  vendorNames: Record<string, string>;
  limit?: number;
}) {
  const rows = entries.filter((entry) => entry.status === "ok" || entry.status === "exhausted");
  const shown = limit ? rows.slice(-limit) : rows;

  if (shown.length === 0) {
    return <p className="px-1 py-6 text-sm text-muted">Nothing has happened yet.</p>;
  }

  return (
    <ol className="space-y-0">
      {shown
        .slice()
        .reverse()
        .map((entry) => {
          const subject =
            vendorNames[String(entry.payload.vendor_id ?? "")] ??
            (entry.payload.node_key as string | undefined) ??
            "";
          const notable = NOTABLE.has(entry.type);
          return (
            <li
              key={entry.id}
              className="flex animate-slide-in items-baseline gap-3 border-b border-rule/60 py-2 last:border-0"
            >
              <time className="figure shrink-0 text-2xs text-faint">
                {formatTimestamp(entry.recorded_at).slice(11)}
              </time>
              <span
                className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                  entry.status === "exhausted"
                    ? "bg-rose"
                    : notable
                      ? "bg-petrol"
                      : "bg-rule"
                }`}
                aria-hidden
              />
              <div className="min-w-0 flex-1">
                <p className={`text-sm ${notable ? "text-ink" : "text-muted"}`}>
                  {EVENT_COPY[entry.type] ?? entry.type}
                  {subject && <span className="text-faint"> · {subject}</span>}
                </p>
                {entry.error && <p className="text-2xs text-rose">{entry.error}</p>}
              </div>
              {entry.latency_ms !== null && entry.latency_ms > 800 && (
                <span className="figure shrink-0 text-2xs text-faint">
                  {(entry.latency_ms / 1000).toFixed(1)}s
                </span>
              )}
            </li>
          );
        })}
    </ol>
  );
}
