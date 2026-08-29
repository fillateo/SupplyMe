"use client";

import type { SupplyChainNode, Vendor } from "@/lib/types";

/*
 * The decomposition is the first thing the agent decides and the thing a reader
 * most needs to sanity-check, so it is shown as a list of what must be sourced
 * with how many candidates each has — not as a tree diagram, which would imply
 * a dependency structure most of these nodes do not have.
 */
export function SupplyChain({
  nodes,
  vendors,
}: {
  nodes: SupplyChainNode[];
  vendors: Vendor[];
}) {
  if (nodes.length === 0) {
    return <p className="py-8 text-sm text-muted">Still reading the objective.</p>;
  }

  const consolidators = vendors.filter((vendor) => vendor.node_keys.length > 1);

  return (
    <div className="space-y-6">
      <ul className="divide-y divide-rule border-y border-rule">
        {nodes.map((node) => {
          const candidates = vendors.filter((vendor) => vendor.node_keys.includes(node.key));
          const qualified = candidates.filter((v) => v.status === "qualified");
          return (
            <li key={node.id} className="py-4">
              <div className="flex items-start justify-between gap-6">
                <div className="min-w-0">
                  <h3 className="text-sm font-medium text-ink">
                    {node.name}
                    {!node.required && (
                      <span className="ml-2 font-mono text-2xs uppercase tracking-[0.08em] text-faint">
                        optional
                      </span>
                    )}
                  </h3>
                  {node.rationale && (
                    <p className="mt-1 max-w-xl text-xs leading-relaxed text-muted">
                      {node.rationale}
                    </p>
                  )}
                  {node.consolidates_with.length > 0 && (
                    <p className="mt-1.5 font-mono text-2xs uppercase tracking-[0.08em] text-faint">
                      one supplier might also cover {node.consolidates_with.join(", ")}
                    </p>
                  )}
                </div>
                <div className="shrink-0 text-right">
                  <p className="figure text-sm">
                    {qualified.length}
                    <span className="text-faint">/{candidates.length}</span>
                  </p>
                  <p className="col-label">qualified</p>
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      {consolidators.length > 0 && (
        <section className="card p-5">
          <h3 className="col-label">Suppliers covering more than one category</h3>
          <p className="mt-1.5 text-xs text-muted">
            Fewer suppliers means fewer relationships to manage on a first run.
          </p>
          <ul className="mt-3 space-y-1.5">
            {consolidators.map((vendor) => (
              <li key={vendor.id} className="flex items-baseline justify-between gap-4">
                <span className="text-sm text-ink">{vendor.name}</span>
                <span className="font-mono text-2xs uppercase tracking-[0.08em] text-muted">
                  {vendor.node_keys.join(" · ")}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
