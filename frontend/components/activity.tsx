"use client";

import type { ActivityEntry } from "@/lib/types";
import { formatClock } from "./evidence-drawer";

/*
 * Real-Time Telemetry Log:
 * Clean chronological activity stream of agent actions,
 * validations, and status transitions.
 */

const EVENT_META: Record<string, { label: string; icon: string }> = {
  "mission.created": { label: "Mission Initialized", icon: "✦" },
  "requirements.created": { label: "Objective Decomposed", icon: "⚙" },
  "supply_chain.planned": { label: "BOM Generated", icon: "▥" },
  "supplier.discovery.started": { label: "Search Dispatched", icon: "⌕" },
  "vendor.discovered": { label: "Candidate Found", icon: "⚑" },
  "vendor.research.started": { label: "Profile Scraped", icon: "≡" },
  "evidence.found": { label: "Evidence Verified", icon: "✓" },
  "brand.claim.found": { label: "Brand Relationship Found", icon: "🏷" },
  "brand.claim.adjudicated": { label: "Brand Claim Verified", icon: "⚖" },
  "vendor.qualified": { label: "Supplier Qualified", icon: "✓✓" },
  "vendor.rejected": { label: "Supplier Disqualified", icon: "✕" },
  "vendor.contact.required": { label: "Outreach Required", icon: "✉" },
  "email.draft.created": { label: "Inquiry Drafted", icon: "✎" },
  "approval.requested": { label: "Authorization Required", icon: "✋" },
  "approval.granted": { label: "Outreach Approved", icon: "✓" },
  "approval.denied": { label: "Outreach Cancelled", icon: "✕" },
  "email.sent": { label: "Email Dispatched", icon: "↗" },
  "email.received": { label: "Supplier Replied", icon: "↙" },
  "quote.extracted": { label: "Quote Extracted", icon: "$" },
  "conflict.detected": { label: "Discrepancy Detected", icon: "⚡" },
  "followup.required": { label: "Follow-up Sent", icon: "↻" },
  "vendor.updated": { label: "Dossier Updated", icon: "∷" },
  "recommendation.ready": { label: "Rankings Computed", icon: "★" },
  "mission.completed": { label: "Mission Completed", icon: "✔" },
  "mission.failed": { label: "Execution Stopped", icon: "⚠" },
};

const HIGH_PRIORITY_EVENTS = new Set([
  "conflict.detected",
  "email.received",
  "brand.claim.adjudicated",
  "recommendation.ready",
  "mission.completed",
  "approval.requested",
  "vendor.qualified",
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
  const rows = entries.filter(
    (entry) => entry.status === "ok" || entry.status === "exhausted",
  );
  const shown = limit ? rows.slice(-limit) : rows;

  if (shown.length === 0) {
    return (
      <div className="py-6 text-center">
        <p className="text-xs text-slate-400">Awaiting first telemetry event…</p>
      </div>
    );
  }

  return (
    <ol className="divide-y divide-slate-100">
      {shown
        .slice()
        .reverse()
        .map((entry) => {
          const subject =
            vendorNames[String(entry.payload.vendor_id ?? "")] ??
            (entry.payload.node_key as string | undefined)?.replace(/-/g, " ") ??
            "";

          const meta = EVENT_META[entry.type] ?? {
            label: entry.type.replace(/\./g, " "),
            icon: "•",
          };

          const isNotable = HIGH_PRIORITY_EVENTS.has(entry.type);
          const isFailed = entry.status === "exhausted";
          const isConflict = entry.type === "conflict.detected" || entry.type === "approval.requested";

          let dotColor = "bg-slate-300";
          if (isFailed) {
            dotColor = "bg-rose-500";
          } else if (isConflict) {
            dotColor = "bg-amber-500";
          } else if (isNotable) {
            dotColor = "bg-blue-600";
          }

          return (
            <li
              key={entry.id}
              className={`flex items-start gap-2.5 py-2 transition-colors ${
                isNotable ? "bg-slate-50/80 -mx-1.5 px-1.5 rounded-md" : ""
              }`}
            >
              {/* Event Timestamp */}
              <time className="w-13 shrink-0 pt-0.5 font-mono text-[0.65rem] text-slate-400">
                {formatClock(entry.recorded_at)}
              </time>

              {/* Status Dot */}
              <div className="pt-1.5 shrink-0">
                <span className={`block h-1.5 w-1.5 rounded-full ${dotColor}`} aria-hidden />
              </div>

              {/* Content Description */}
              <div className="min-w-0 flex-1">
                <p
                  className={`text-xs leading-snug ${
                    isNotable ? "font-semibold text-slate-900" : "text-slate-600"
                  }`}
                >
                  <span>{meta.label}</span>
                  {subject && (
                    <span className="font-semibold text-slate-800"> · {subject}</span>
                  )}
                </p>

                {entry.error && (
                  <p className="mt-1 font-mono text-xs text-rose-700 rounded bg-rose-50 p-1 border border-rose-200">
                    {entry.error}
                  </p>
                )}
              </div>

              {/* Latency Metric */}
              {entry.latency_ms !== null && entry.latency_ms > 400 && (
                <span className="shrink-0 pt-0.5 font-mono text-[0.65rem] text-slate-400">
                  {(entry.latency_ms / 1000).toFixed(1)}s
                </span>
              )}
            </li>
          );
        })}
    </ol>
  );
}


