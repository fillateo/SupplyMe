"use client";

import type { Conflict } from "@/lib/types";

//: Keyed by Conflict.resolution_action. Deliberately phrased as what will
//: happen rather than what has: this line renders while a conflict is still
//: `open`, before anything has been written to anybody.
const ACTION_COPY: Record<string, string> = {
  email: "This will be put to the supplier in a follow-up",
  none: "There is no way to ask the supplier about it",
};

const STATUS_META: Record<string, { label: string; badge: string }> = {
  open: {
    label: "Sources differ",
    badge: "bg-rose-50 text-rose-700 border-rose-200",
  },
  resolving: {
    label: "Asking the supplier",
    badge: "bg-amber-50 text-amber-700 border-amber-200",
  },
  resolved: {
    label: "Resolved",
    badge: "bg-emerald-50 text-emerald-700 border-emerald-200",
  },
  unresolvable: {
    label: "Left unresolved",
    badge: "bg-slate-100 text-slate-600 border-slate-200",
  },
};

export function ConflictNotice({ conflict }: { conflict: Conflict }) {
  const settled = conflict.status === "resolved";
  const meta = STATUS_META[conflict.status] ?? STATUS_META.open;

  return (
    <section
      className={`overflow-hidden rounded-lg border p-4 transition-all ${
        settled
          ? "border-emerald-200 bg-emerald-50/40"
          : "border-amber-200 bg-amber-50/30"
      }`}
    >
      <header className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-200/60">
        <div className="flex items-center gap-2">
          <span className={`rounded px-2 py-0.5 text-xs font-semibold border ${meta.badge}`}>
            {meta.label}
          </span>
          <span className="text-xs font-semibold text-slate-800 capitalize">
            {conflict.field.replace(/_/g, " ")}
          </span>
        </div>
      </header>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {conflict.values.map((entry, index) => (
          <div
            key={index}
            className="rounded-lg border border-slate-200 bg-white p-3 shadow-subtle"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-slate-500 capitalize">
                Source: {entry.source_type.replace(/_/g, " ")}
              </span>
              <span className="text-xs font-semibold text-slate-400">Variant #{index + 1}</span>
            </div>
            <p className="mt-1 text-base font-bold text-slate-900 font-mono">
              {String(entry.value)}
            </p>
            {entry.excerpt && (
              <p className="mt-2 line-clamp-3 rounded bg-slate-50 p-2 font-mono text-xs italic leading-relaxed text-slate-600 border-l-2 border-slate-300">
                “{entry.excerpt}”
              </p>
            )}
          </div>
        ))}
      </div>

      <div className="mt-3 rounded-lg bg-white p-3 border border-slate-200 text-xs leading-relaxed text-slate-700">
        {settled ? (
          <p className="flex items-start gap-2">
            <span className="text-emerald-600 font-bold">✓</span>
            <span>
              Settled as{" "}
              <strong className="text-emerald-700 font-mono font-semibold">
                {String(conflict.resolved_value)}
              </strong>{" "}
              — {conflict.preferred_reason}
            </span>
          </p>
        ) : (
          <p className="flex items-start gap-2">
            <span className="text-amber-600 font-bold">⚠</span>
            <span>
              Using provisional figure{" "}
              <strong className="text-slate-900 font-mono font-semibold">
                {String(conflict.preferred_value)}
              </strong>{" "}
              ({conflict.preferred_reason}).{" "}
              <span className="text-slate-500">{ACTION_COPY[conflict.resolution_action ?? "none"]}</span>.
            </span>
          </p>
        )}
      </div>
    </section>
  );
}


