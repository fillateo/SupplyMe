"use client";

import type { SupplyChainNode, Vendor } from "@/lib/types";

/*
 * The supply chain the planning agent derived, one card per component line,
 * each showing how far its candidates have got.
 */

const STAGE_META: Record<string, { fill: string; label: string; order: number }> = {
  discovered: {
    fill: "bg-slate-400",
    label: "Discovered",
    order: 0,
  },
  researching: {
    fill: "bg-blue-500",
    label: "Researching",
    order: 1,
  },
  shortlisted: {
    fill: "bg-indigo-500",
    label: "Shortlisted",
    order: 2,
  },
  contacted: {
    fill: "bg-amber-500",
    label: "Outreach Sent",
    order: 3,
  },
  responded: {
    fill: "bg-emerald-500",
    label: "Replied",
    order: 4,
  },
  qualified: {
    fill: "bg-emerald-600",
    label: "Qualified",
    order: 5,
  },
  rejected: {
    fill: "bg-slate-300",
    label: "Ruled Out",
    order: -1,
  },
};

const LEGEND_ITEMS = [
  "discovered",
  "researching",
  "shortlisted",
  "contacted",
  "responded",
  "qualified",
  "rejected",
] as const;

function CandidateStrip({ candidates }: { candidates: Vendor[] }) {
  if (candidates.length === 0) {
    return (
      <div className="mt-3 flex items-center gap-2.5">
        <span
          className="h-2 w-full max-w-[14rem] rounded-full bg-slate-100"
          aria-hidden
        />
        <span className="shrink-0 text-xs text-slate-400">No candidates found yet</span>
      </div>
    );
  }

  const ordered = [...candidates].sort(
    (a, b) => (STAGE_META[b.status]?.order ?? 0) - (STAGE_META[a.status]?.order ?? 0),
  );

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
      <div
        className="flex max-w-[14rem] flex-1 gap-1 p-1 rounded-md bg-slate-100 border border-slate-200"
        role="img"
        aria-label={`${candidates.length} candidates`}
      >
        {ordered.map((vendor) => {
          const meta = STAGE_META[vendor.status] ?? STAGE_META.discovered;
          return (
            <span
              key={vendor.id}
              title={`${vendor.name} — ${meta.label}`}
              className={`h-2 min-w-[8px] flex-1 rounded-[2px] cursor-help transition-all ${meta.fill}`}
            />
          );
        })}
      </div>
      <span className="shrink-0 text-xs font-medium text-slate-600">
        {candidates.length} {candidates.length === 1 ? "candidate" : "candidates"} in pipeline
      </span>
    </div>
  );
}

export function SupplyChain({
  nodes,
  vendors,
  live = false,
}: {
  nodes: SupplyChainNode[];
  vendors: Vendor[];
  live?: boolean;
}) {
  if (nodes.length === 0) {
    return (
      <div className="card p-12 text-center border-dashed bg-white">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-blue-50 text-blue-600 font-bold">
          ⚙
        </div>
        <p className="text-base font-semibold text-slate-800">Decomposing Bill of Materials</p>
        <p className="mx-auto mt-1.5 max-w-md text-xs leading-relaxed text-slate-500">
          {live
            ? "Working out which components this product needs before anything is searched for."
            : "This mission terminated before the bill of materials could be decomposed."}
        </p>
      </div>
    );
  }

  const consolidators = vendors.filter((vendor) => vendor.node_keys.length > 1);

  return (
    <div className="space-y-6">
      {/* BOM Header & Pipeline Legend */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 pb-3 border-b border-slate-200">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Bill of Materials Architecture
            </h2>
            <p className="text-xs text-slate-500">
              {nodes.length} component line{nodes.length === 1 ? "" : "s"} required for complete production
            </p>
          </div>

          <ul className="flex flex-wrap items-center gap-x-3 gap-y-1.5 p-2 rounded-lg bg-slate-50 border border-slate-200 text-xs">
            {LEGEND_ITEMS.map((key) => {
              const meta = STAGE_META[key];
              return (
                <li key={key} className="flex items-center gap-1.5 font-medium text-slate-600">
                  <span className={`h-2 w-2 rounded-full ${meta.fill}`} aria-hidden />
                  {meta.label}
                </li>
              );
            })}
          </ul>
        </div>

        {/* Numbered BOM Cards */}
        <ol className="space-y-3">
          {nodes.map((node, index) => {
            const candidates = vendors.filter((vendor) => vendor.node_keys.includes(node.key));
            const qualified = candidates.filter((vendor) => vendor.status === "qualified");
            const hasQualified = qualified.length > 0;

            return (
              <li
                key={node.id}
                className={`card p-5 transition-all ${
                  hasQualified
                    ? "border-emerald-300 ring-1 ring-emerald-200 bg-white"
                    : "hover:border-slate-300 bg-white"
                }`}
              >
                <div className="flex items-start gap-4">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 font-mono text-xs font-bold text-slate-700">
                    {String(index + 1).padStart(2, "0")}
                  </span>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex items-center gap-2.5">
                        <h3 className="text-base font-semibold text-slate-900">
                          {node.name}
                        </h3>
                        {!node.required && (
                          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 border border-slate-200">
                            Optional Component
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-2">
                        <span
                          className={`rounded px-2.5 py-0.5 text-xs font-semibold ${
                            hasQualified
                              ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                              : "bg-slate-100 text-slate-600 border border-slate-200"
                          }`}
                        >
                          {qualified.length} Qualified
                        </span>
                      </div>
                    </div>

                    {node.rationale && (
                      <p className="mt-1 text-xs leading-relaxed text-slate-600">
                        {node.rationale}
                      </p>
                    )}

                    <CandidateStrip candidates={candidates} />

                    {node.consolidates_with.length > 0 && (
                      <p className="mt-2 text-xs text-indigo-700 font-medium">
                        ✦ Multi-line consolidation potential with:{" "}
                        {node.consolidates_with.map((key) => key.replace(/-/g, " ")).join(", ")}
                      </p>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      {/* Multi-Node Consolidators */}
      {consolidators.length > 0 && (
        <section className="card p-5 border-indigo-200 bg-indigo-50/40">
          <div className="flex items-center gap-2">
            <span className="text-indigo-600 text-base">✦</span>
            <h3 className="text-sm font-semibold text-indigo-950">
              Suppliers covering more than one line
            </h3>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-indigo-900/80">
These suppliers said they can cover more than one component line. Fewer suppliers means fewer conversations to run and fewer quotes to reconcile — the system does not assess shipping or compliance.
          </p>

          <ul className="mt-3.5 space-y-2 divide-y divide-indigo-100">
            {consolidators.map((vendor) => (
              <li
                key={vendor.id}
                className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 pt-2 first:pt-0"
              >
                <div>
                  <span className="font-semibold text-slate-900">{vendor.name}</span>
                  <span className="ml-2 text-xs text-slate-500 font-mono">
                    ({vendor.city ?? "Location unverified"})
                  </span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {vendor.node_keys.map((key) => (
                    <span
                      key={key}
                      className="rounded bg-indigo-100/80 px-2 py-0.5 text-xs font-medium text-indigo-800 border border-indigo-200"
                    >
                      {key.replace(/-/g, " ")}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}


