"use client";

import type { Conflict } from "@/lib/types";

const ACTION_COPY: Record<string, string> = {
  call: "Calling the supplier to settle it",
  email: "Asking the supplier to confirm",
  none: "No route to settle it",
};

const STATUS_COPY: Record<string, string> = {
  open: "Detected",
  resolving: "Being settled",
  resolved: "Settled",
  unresolvable: "Could not be settled",
};

/**
 * Two sources disagreeing is the most useful thing this product finds, so it
 * gets its own device rather than a warning icon: both values, side by side,
 * each labelled with where it came from, and what the system did about it.
 */
export function ConflictNotice({ conflict }: { conflict: Conflict }) {
  const settled = conflict.status === "resolved";
  const tone = settled ? "border-petrol bg-petrol-light/40" : "border-rose bg-rose-light/50";

  return (
    <section className={`rounded-md border-l-2 ${tone} px-4 py-3`}>
      <header className="flex items-baseline justify-between gap-3">
        <h4 className="font-mono text-2xs uppercase tracking-[0.1em] text-ink">
          {STATUS_COPY[conflict.status] ?? conflict.status} · {conflict.field.replace(/_/g, " ")}
        </h4>
        {!settled && <span className="h-3 w-8 rounded-sm hatch" aria-hidden />}
      </header>

      <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
        {conflict.values.map((entry, index) => (
          <div key={index} className="rounded-sm bg-surface/80 px-3 py-2">
            <p className="figure text-sm">{String(entry.value)}</p>
            <p className="col-label mt-0.5">{entry.source_type.replace(/_/g, " ")}</p>
            {entry.excerpt && (
              <p className="mt-1.5 line-clamp-2 font-serif text-xs italic text-muted">
                &ldquo;{entry.excerpt}&rdquo;
              </p>
            )}
          </div>
        ))}
      </div>

      <p className="mt-2.5 text-xs text-muted">
        {settled ? (
          <>
            Now recorded as{" "}
            <span className="figure text-ink">{String(conflict.resolved_value)}</span> —{" "}
            {conflict.preferred_reason}
          </>
        ) : (
          <>
            Using{" "}
            <span className="figure text-ink">{String(conflict.preferred_value)}</span> meanwhile,
            because {conflict.preferred_reason}.{" "}
            {ACTION_COPY[conflict.resolution_action ?? "none"]}.
          </>
        )}
      </p>
    </section>
  );
}
