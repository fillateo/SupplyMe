"use client";

import type { Dimension, Fact, Provenance, Trust } from "@/lib/types";

/*
 * How a displayed fact was obtained.
 *
 * Every state here is one app/domain/evidence.py can actually produce. Two that
 * it cannot used to be listed anyway — including an "Estimated / by the AI
 * reasoning engine" badge, which describes the opposite of how this system
 * works: the model extracts claims and never rates them.
 */

type MarkStyle = { label: string; className: string; icon: string; hint: string };

const PROVENANCE: Record<Provenance, MarkStyle> = {
  verified: {
    label: "Corroborated",
    icon: "✓✓",
    className: "bg-emerald-50 text-emerald-700 border-emerald-200",
    hint: "Two or more independent sources agree on this fact.",
  },
  direct_quote: {
    label: "In Writing",
    icon: "✉",
    className: "bg-blue-50 text-blue-700 border-blue-200",
    hint: "The supplier stated this directly in written correspondence we hold.",
  },
  publicly_listed: {
    label: "Published",
    icon: "🌐",
    className: "bg-slate-100 text-slate-700 border-slate-200",
    hint: "Published on a page we read — the supplier's own site, or a listing about them.",
  },
  inferred: {
    label: "Inferred",
    icon: "∷",
    className: "bg-purple-50 text-purple-700 border-purple-200",
    hint: "Supported only by sources too weak to count as published or corroborated.",
  },
  conflicting: {
    label: "Sources differ",
    icon: "⚡",
    className: "bg-rose-50 text-rose-700 border-rose-200",
    hint: "Two sources give different values. The better-sourced one is shown.",
  },
  unknown: {
    label: "Unknown",
    icon: "—",
    className: "bg-slate-50 text-slate-500 border-slate-200",
    hint: "No source has answered this yet.",
  },
};

export function ProvenanceMark({ provenance }: { provenance: Provenance }) {
  const style = PROVENANCE[provenance] ?? PROVENANCE.unknown;
  return (
    <span
      title={style.hint}
      className={`inline-flex shrink-0 items-center gap-1 rounded px-2 py-0.5 text-xs font-medium border ${style.className}`}
    >
      <span className="opacity-70 text-[0.65rem]">{style.icon}</span>
      {style.label}
    </span>
  );
}

/**
 * Clean linear progress meter designed for high readability.
 */
export function ConfidenceMeter({
  value,
  tone = "green",
}: {
  value: number;
  tone?: "blue" | "green" | "amber" | "rose" | "purple" | "cyan";
}) {
  const clamped = Math.max(0, Math.min(1, value));
  const percent = Math.round(clamped * 100);

  const fillColors: Record<string, string> = {
    blue: "bg-blue-600",
    cyan: "bg-sky-500",
    green: "bg-emerald-600",
    amber: "bg-amber-500",
    rose: "bg-rose-500",
    purple: "bg-purple-600",
  };

  const fillColor = fillColors[tone] ?? fillColors.green;

  return (
    <div
      className="inline-flex items-center gap-2"
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className="h-2 w-16 overflow-hidden rounded-full bg-slate-100 border border-slate-200/80">
        <div
          className={`h-full rounded-full transition-all duration-300 ${fillColor}`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function toneFor(score: number): "green" | "blue" | "amber" | "rose" {
  if (score >= 0.75) return "green";
  if (score >= 0.5) return "blue";
  if (score >= 0.25) return "amber";
  return "rose";
}

export function TrustBreakdown({ trust }: { trust: Trust }) {
  return (
    <div className="space-y-3 rounded-lg bg-slate-50/80 p-3.5 border border-slate-200">
      <div className="flex items-center justify-between pb-2 border-b border-slate-200">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Evidence by dimension
        </span>
        <span className="text-xs font-bold text-slate-900 font-mono">
          Overall: {Math.round(trust.overall * 100)}%
        </span>
      </div>
      <dl className="space-y-2">
        {trust.dimensions.map((dimension: Dimension) => {
          const tone = toneFor(dimension.score);
          const percent = Math.round(dimension.score * 100);
          return (
            <div
              key={dimension.name}
              className="grid grid-cols-[7.5rem_auto_3rem_1fr] items-center gap-x-3 gap-y-1 max-sm:grid-cols-[1fr_auto] max-sm:gap-y-1"
            >
              <dt className="text-xs font-medium text-slate-700 truncate capitalize max-sm:col-span-2">
                {dimension.name.replace(/_/g, " ")}
              </dt>
              <ConfidenceMeter value={dimension.score} tone={tone} />
              <span
                className={`text-right text-xs font-semibold font-mono ${
                  percent >= 70
                    ? "text-emerald-700"
                    : percent >= 40
                    ? "text-amber-700"
                    : "text-rose-700"
                }`}
              >
                {percent}%
              </span>
              <span className="truncate text-xs text-slate-500 max-sm:col-span-2">
                {dimension.explanation}
              </span>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

/** A figure with evidence proof trigger */
export function SourcedFigure({
  fact,
  format,
  unknownLabel = "Not established",
  onOpen,
}: {
  fact: Fact;
  format?: (value: string | number) => string;
  unknownLabel?: string;
  onOpen?: (evidenceIds: string[], label: string) => void;
}) {
  const known = fact.value !== null && fact.provenance !== "unknown";
  if (!known) {
    return <span className="text-xs text-slate-400 italic">{unknownLabel}</span>;
  }
  const rendered = format ? format(fact.value as string | number) : String(fact.value);
  const clickable = Boolean(onOpen) && fact.evidence_ids.length > 0;

  const figure = clickable ? (
    <button
      type="button"
      onClick={() => onOpen!(fact.evidence_ids, rendered)}
      className="sourced"
      title={`Inspect ${fact.evidence_ids.length} evidence source${
        fact.evidence_ids.length === 1 ? "" : "s"
      }`}
    >
      <span>{rendered}</span>
      <span className="ml-1 text-[0.65rem] opacity-75 font-mono">[{fact.evidence_ids.length}]</span>
    </button>
  ) : (
    <span className="text-xs font-semibold text-slate-800 font-mono">{rendered}</span>
  );

  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {figure}
      <ProvenanceMark provenance={fact.provenance} />
    </span>
  );
}

/*
 * Status chip with clean, soft background styling and accessible contrast.
 */
const STATUS_STYLES: Record<string, { label: string; tone: string; dotColor: string }> = {
  // Vendor pipeline
  discovered: {
    label: "Discovered",
    tone: "bg-slate-100 text-slate-700 border-slate-200",
    dotColor: "bg-slate-500",
  },
  researching: {
    label: "Researching",
    tone: "bg-blue-50 text-blue-700 border-blue-200",
    dotColor: "bg-blue-500",
  },
  shortlisted: {
    label: "Shortlisted",
    tone: "bg-indigo-50 text-indigo-700 border-indigo-200",
    dotColor: "bg-indigo-500",
  },
  contacted: {
    label: "Outreach Sent",
    tone: "bg-amber-50 text-amber-700 border-amber-200",
    dotColor: "bg-amber-500",
  },
  responded: {
    label: "Replied",
    tone: "bg-emerald-50 text-emerald-700 border-emerald-200",
    dotColor: "bg-emerald-500",
  },
  qualified: {
    label: "Qualified",
    tone: "bg-emerald-100 text-emerald-800 border-emerald-300 font-semibold",
    dotColor: "bg-emerald-600",
  },
  rejected: {
    label: "Ruled Out",
    tone: "bg-slate-100 text-slate-500 border-slate-200",
    dotColor: "bg-slate-400",
  },

  // Mission lifecycle
  created: {
    label: "Initialized",
    tone: "bg-slate-100 text-slate-700 border-slate-200",
    dotColor: "bg-slate-400",
  },
  planning: {
    label: "BOM Planning",
    tone: "bg-purple-50 text-purple-700 border-purple-200",
    dotColor: "bg-purple-500",
  },
  discovering: {
    label: "Active Discovery",
    tone: "bg-blue-50 text-blue-700 border-blue-200",
    dotColor: "bg-blue-500",
  },
  outreach: {
    label: "Outreach in Progress",
    tone: "bg-amber-50 text-amber-700 border-amber-200",
    dotColor: "bg-amber-500",
  },
  awaiting_response: {
    label: "Awaiting Replies",
    tone: "bg-amber-50 text-amber-700 border-amber-200",
    dotColor: "bg-amber-500",
  },
  awaiting_approval: {
    label: "Decision Required",
    tone: "bg-rose-50 text-rose-700 border-rose-300 font-semibold",
    dotColor: "bg-rose-500",
  },
  recommending: {
    label: "Ranking Suppliers",
    tone: "bg-purple-50 text-purple-700 border-purple-200",
    dotColor: "bg-purple-500",
  },
  completed: {
    label: "Completed",
    tone: "bg-emerald-50 text-emerald-700 border-emerald-200",
    dotColor: "bg-emerald-500",
  },
  failed: {
    label: "Stopped",
    tone: "bg-rose-50 text-rose-700 border-rose-200",
    dotColor: "bg-rose-500",
  },

  // Communications
  sent: {
    label: "Sent",
    tone: "bg-amber-50 text-amber-700 border-amber-200",
    dotColor: "bg-amber-500",
  },
  draft: {
    label: "Drafted",
    tone: "bg-slate-100 text-slate-700 border-slate-200",
    dotColor: "bg-slate-400",
  },
  awaiting: {
    label: "Awaiting Reply",
    tone: "bg-amber-50 text-amber-700 border-amber-200",
    dotColor: "bg-amber-500",
  },
  not_attempted: {
    label: "Not Contacted",
    tone: "bg-slate-100 text-slate-500 border-slate-200",
    dotColor: "bg-slate-400",
  },
};

export function StatusChip({
  status,
  live = false,
}: {
  status: string;
  live?: boolean;
}) {
  const meta = STATUS_STYLES[status] ?? {
    label: status.replace(/_/g, " "),
    tone: "bg-slate-100 text-slate-700 border-slate-200",
    dotColor: "bg-blue-500",
  };

  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border ${meta.tone}`}
    >
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${meta.dotColor} ${live ? "animate-pulse" : ""}`} />
      <span>{meta.label}</span>
    </span>
  );
}

export function formatMoney(value: number | string, currency = "IDR"): string {
  const amount = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(amount)) return String(value);
  return `${currency} ${amount.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function formatDays(value: number | string): string {
  const days = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(days)) return String(value);
  return `${days} ${days === 1 ? "day" : "days"}`;
}

export function formatUnits(value: number | string): string {
  const units = typeof value === "number" ? value : Number(value);
  return Number.isNaN(units) ? String(value) : units.toLocaleString("en-US");
}


