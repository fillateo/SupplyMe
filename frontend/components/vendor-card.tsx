"use client";

import type { Vendor } from "@/lib/types";
import { ConflictNotice } from "./conflict";
import {
  ProvenanceStamp, SourcedFigure, StatusChip, TrustBreakdown,
  formatDays, formatMoney, formatUnits,
} from "./primitives";

const BRAND_COPY: Record<string, { label: string; tone: string; meaning: string }> = {
  verified: {
    label: "Verified", tone: "bg-petrol-light text-petrol-deep",
    meaning: "the brand's own site confirms it",
  },
  strong_evidence: {
    label: "Strong evidence", tone: "bg-petrol-light text-petrol-deep",
    meaning: "independent publications name both",
  },
  indirect_evidence: {
    label: "Indirect evidence", tone: "bg-amber-light text-amber",
    meaning: "related sources, none stating it outright",
  },
  supplier_reported: {
    label: "Supplier's word only", tone: "bg-amber-light text-amber",
    meaning: "nothing independent was found",
  },
  unverified: {
    label: "Unverified", tone: "bg-slate2-light text-muted", meaning: "not established",
  },
  no_public_evidence: {
    label: "No public evidence", tone: "bg-slate2-light text-muted",
    meaning: "nothing found at all",
  },
};

export function VendorCard({
  vendor,
  expanded,
  onToggle,
  onOpenEvidence,
}: {
  vendor: Vendor;
  expanded: boolean;
  onToggle: () => void;
  onOpenEvidence: (evidenceIds: string[], label: string) => void;
}) {
  const currency = vendor.currency ?? "IDR";
  const openConflicts = vendor.conflicts.filter((c) => c.status !== "resolved");

  return (
    <article
      className={`card overflow-hidden ${vendor.status === "rejected" ? "opacity-75" : ""}`}
    >
      <button
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-start justify-between gap-4 px-5 py-4 text-left hover:bg-paper/50"
      >
        <div className="min-w-0">
          <h3 className="truncate text-base font-medium text-ink">{vendor.name}</h3>
          <p className="mt-0.5 font-mono text-2xs uppercase tracking-[0.08em] text-faint">
            {[vendor.city, vendor.country].filter(Boolean).join(", ") || "location unknown"}
            {vendor.node_keys.length > 0 && ` · supplies ${vendor.node_keys.join(", ")}`}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {openConflicts.length > 0 && (
            <span className="rounded-sm bg-rose-light px-1.5 py-0.5 font-mono text-2xs uppercase tracking-[0.08em] text-rose">
              {openConflicts.length} disagreement{openConflicts.length > 1 ? "s" : ""}
            </span>
          )}
          <StatusChip status={vendor.status} />
        </div>
      </button>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-t border-rule px-5 py-4 sm:grid-cols-4">
        <Figure label="Minimum order">
          <SourcedFigure fact={vendor.moq} format={formatUnits} onOpen={onOpenEvidence} />
        </Figure>
        <Figure label="Unit price">
          <SourcedFigure
            fact={vendor.unit_price}
            format={(value) => formatMoney(value, currency)}
            onOpen={onOpenEvidence}
          />
        </Figure>
        <Figure label="Lead time">
          <SourcedFigure fact={vendor.lead_time_days} format={formatDays} onOpen={onOpenEvidence} />
        </Figure>
        <Figure label="Evidence">
          <span className="figure text-sm">{Math.round(vendor.trust.overall * 100)}%</span>
        </Figure>
      </dl>

      {vendor.rejection_reasons.length > 0 && (
        <p className="border-t border-rule bg-paper/60 px-5 py-3 text-xs text-muted">
          <span className="col-label mr-2">Ruled out</span>
          {vendor.rejection_reasons.join("; ")}
        </p>
      )}

      {expanded && (
        <div className="space-y-5 border-t border-rule px-5 py-5">
          {openConflicts.length + vendor.conflicts.length > 0 && (
            <section className="space-y-2">
              <h4 className="col-label">Where sources disagree</h4>
              {vendor.conflicts.map((conflict) => (
                <ConflictNotice key={conflict.id} conflict={conflict} />
              ))}
            </section>
          )}

          {vendor.brand_relationships.length > 0 && (
            <section>
              <h4 className="col-label mb-2">Claimed customers</h4>
              <ul className="space-y-2">
                {vendor.brand_relationships.map((relationship) => {
                  const copy = BRAND_COPY[relationship.classification] ?? BRAND_COPY.unverified;
                  return (
                    <li
                      key={relationship.id}
                      className="flex items-baseline justify-between gap-3 rounded-sm bg-paper/60 px-3 py-2"
                    >
                      <span className="text-sm text-ink">{relationship.brand}</span>
                      <span className="flex items-center gap-2">
                        <span className="text-xs text-muted">{copy.meaning}</span>
                        <span
                          className={`rounded-sm px-1.5 py-0.5 font-mono text-2xs uppercase tracking-[0.08em] ${copy.tone}`}
                        >
                          {copy.label}
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          <section>
            <h4 className="col-label mb-2">How much of this is established</h4>
            <TrustBreakdown trust={vendor.trust} />
          </section>

          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            <Figure label="Sample lead time">
              <SourcedFigure
                fact={vendor.sample_lead_time_days} format={formatDays} onOpen={onOpenEvidence}
              />
            </Figure>
            <Figure label="Payment terms">
              <SourcedFigure fact={vendor.payment_terms} onOpen={onOpenEvidence} />
            </Figure>
            <Figure label="Customization">
              <SourcedFigure fact={vendor.customization} onOpen={onOpenEvidence} />
            </Figure>
            <Figure label="Contact">
              <span className="font-mono text-xs text-muted">
                {vendor.email ?? vendor.phone ?? "none found"}
              </span>
            </Figure>
          </dl>

          {vendor.missing_fields.length > 0 && (
            <p className="text-xs text-muted">
              <span className="col-label mr-2">Still unanswered</span>
              {vendor.missing_fields.map((f) => f.replace(/_/g, " ")).join(", ")}
            </p>
          )}

          {vendor.website && (
            <a
              href={vendor.website}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-block font-mono text-xs text-petrol underline decoration-dotted underline-offset-4"
            >
              {vendor.website}
            </a>
          )}
        </div>
      )}
    </article>
  );
}

function Figure({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="col-label">{label}</dt>
      <dd className="mt-1">{children}</dd>
    </div>
  );
}
