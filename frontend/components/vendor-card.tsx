"use client";

import type { Vendor } from "@/lib/types";
import { ConflictNotice } from "./conflict";
import {
  ConfidenceMeter,
  SourcedFigure,
  StatusChip,
  TrustBreakdown,
  formatDays,
  formatMoney,
  formatUnits,
} from "./primitives";

/*
 * What a "we produce for Brand X" claim is actually supported by. The wording
 * here has to match what app/domain/evidence.py::classify_brand_relationship
 * measures — which is the source of each mention, and nothing else.
 */
const BRAND_COPY: Record<string, { label: string; tone: string; meaning: string }> = {
  verified: {
    label: "Brand Site Verified",
    tone: "bg-emerald-50 text-emerald-700 border-emerald-200",
    meaning: "The brand's own website states the relationship",
  },
  strong_evidence: {
    label: "Independently Reported",
    tone: "bg-blue-50 text-blue-700 border-blue-200",
    meaning: "Stated by two or more sources that are not the supplier",
  },
  indirect_evidence: {
    label: "Indirect Citation",
    tone: "bg-indigo-50 text-indigo-700 border-indigo-200",
    meaning: "Something other than the supplier mentions it, but does not state it outright",
  },
  supplier_reported: {
    label: "Unverified Claim",
    tone: "bg-amber-50 text-amber-700 border-amber-200",
    meaning: "Claimed by supplier without independent corroboration",
  },
  unverified: {
    label: "Unverified",
    tone: "bg-slate-100 text-slate-600 border-slate-200",
    meaning: "Not verified either way",
  },
  no_public_evidence: {
    label: "No Record Found",
    tone: "bg-slate-100 text-slate-500 border-slate-200",
    meaning: "Nothing outside the supplier's own claim was found",
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
  const ruledOut = vendor.status === "rejected";
  const isQualified = vendor.status === "qualified";
  const openConflicts = vendor.conflicts.filter((conflict) => conflict.status !== "resolved");
  const place = [vendor.city, vendor.country].filter(Boolean).join(", ");
  const trustPercent = Math.round(vendor.trust.overall * 100);

  return (
    <article
      className={`card overflow-hidden transition-all duration-200 ${
        isQualified
          ? "border-emerald-300 ring-1 ring-emerald-200 bg-white"
          : ruledOut
          ? "border-slate-200 bg-slate-50/60 opacity-75"
          : "hover:border-slate-300 bg-white"
      }`}
    >
      <button
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-start justify-between gap-4 p-5 text-left transition-colors hover:bg-slate-50/80"
      >
        <div className="min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h3 className="truncate text-base font-semibold text-slate-900">
              {vendor.name}
            </h3>
            {vendor.website && (
              <span className="font-mono text-xs text-slate-400">
                {vendor.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/.*$/, "")}
              </span>
            )}
          </div>
          <p className="mt-1 flex items-center gap-2 text-xs text-slate-500">
            <span>{place || "Location unknown"}</span>
            {vendor.node_keys.length > 0 && (
              <>
                <span className="text-slate-300">·</span>
                <span className="text-slate-700 font-medium">
                  Supplies: {vendor.node_keys.map((key) => key.replace(/-/g, " ")).join(", ")}
                </span>
              </>
            )}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {openConflicts.length > 0 && (
            <span className="rounded px-2 py-0.5 text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200">
              ⚡ {openConflicts.length} disagreement{openConflicts.length === 1 ? "" : "s"}
            </span>
          )}
          <StatusChip status={vendor.status} />
          <span
            className={`text-slate-400 transition-transform duration-200 text-xs ${
              expanded ? "rotate-180 text-slate-700" : ""
            }`}
            aria-hidden
          >
            ▼
          </span>
        </div>
      </button>

      {/* Main Metric Cards Grid */}
      <dl className="grid grid-cols-2 gap-3 border-t border-slate-100 bg-slate-50/50 p-4 sm:grid-cols-4 sm:px-5">
        <Figure label="Minimum Order Quantity">
          <SourcedFigure fact={vendor.moq} format={formatUnits} onOpen={onOpenEvidence} />
        </Figure>
        <Figure label="Unit Price">
          <SourcedFigure
            fact={vendor.unit_price}
            format={(value) => formatMoney(value, currency)}
            onOpen={onOpenEvidence}
          />
        </Figure>
        <Figure label="Lead Time">
          <SourcedFigure fact={vendor.lead_time_days} format={formatDays} onOpen={onOpenEvidence} />
        </Figure>
        <Figure label="Evidence confidence">
          <div className="flex items-center gap-2">
            <ConfidenceMeter
              value={vendor.trust.overall}
              tone={trustPercent >= 70 ? "green" : trustPercent >= 40 ? "blue" : "amber"}
            />
            <span
              className={`text-xs font-bold font-mono ${
                trustPercent >= 70
                  ? "text-emerald-700"
                  : trustPercent >= 40
                  ? "text-blue-700"
                  : "text-amber-700"
              }`}
            >
              {trustPercent}%
            </span>
          </div>
        </Figure>
      </dl>

      {/* Disqualification Banner */}
      {vendor.rejection_reasons.length > 0 && (
        <div className="border-t border-slate-100 bg-rose-50/60 px-5 py-2.5 text-xs text-rose-800 flex items-start gap-2">
          <span className="font-semibold text-rose-700 shrink-0">Disqualified:</span>
          <span>{vendor.rejection_reasons.join("; ")}</span>
        </div>
      )}

      {/* Expanded Deep Dive Section */}
      {expanded && (
        <div className="animate-rise-in space-y-6 border-t border-slate-200 bg-white p-5 sm:p-6">
          {/* Conflicts Notices */}
          {vendor.conflicts.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-amber-600 text-sm font-bold">⚡</span>
                <h4 className="text-sm font-semibold text-slate-800">Where sources disagree</h4>
              </div>
              {vendor.conflicts.map((conflict) => (
                <ConflictNotice key={conflict.id} conflict={conflict} />
              ))}
            </section>
          )}

          {/* Claimed Brand Relationships */}
          {vendor.brand_relationships.length > 0 && (
            <section className="space-y-3">
              <h4 className="text-sm font-semibold text-slate-800">Brands they claim to work with</h4>
              <div className="space-y-2">
                {groupByClassification(vendor.brand_relationships).map(
                  ([classification, brands]) => {
                    const copy = BRAND_COPY[classification] ?? BRAND_COPY.unverified;
                    return (
                      <div
                        key={classification}
                        className="rounded-lg border border-slate-200 bg-slate-50/50 p-3 space-y-1.5"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span
                            className={`rounded px-2 py-0.5 text-xs font-semibold border ${copy.tone}`}
                          >
                            {copy.label}
                          </span>
                          <span className="text-xs text-slate-500">
                            {brands.length} {brands.length === 1 ? "brand" : "brands"} — {copy.meaning}
                          </span>
                        </div>
                        <p className="font-mono text-xs font-medium text-slate-800">
                          {brands.map((relationship) => relationship.brand).join(", ")}
                        </p>
                      </div>
                    );
                  },
                )}
              </div>
            </section>
          )}

          {/* Trust Score Breakdown */}
          <section className="space-y-2">
            <h4 className="text-sm font-semibold text-slate-800">How confident, and in what</h4>
            <TrustBreakdown trust={vendor.trust} />
          </section>

          {/* Secondary Specifications */}
          <dl className="grid gap-3 sm:grid-cols-2 rounded-lg bg-slate-50 p-4 border border-slate-200">
            <Figure label="Sample Lead Time">
              <SourcedFigure
                fact={vendor.sample_lead_time_days}
                format={formatDays}
                onOpen={onOpenEvidence}
              />
            </Figure>
            <Figure label="Payment Terms">
              <SourcedFigure fact={vendor.payment_terms} onOpen={onOpenEvidence} />
            </Figure>
            <Figure label="Customization">
              <SourcedFigure fact={vendor.customization} onOpen={onOpenEvidence} />
            </Figure>
            <Figure label="Contact route">
              <span className="break-all text-xs font-medium text-slate-800 font-mono">
                {vendor.email ?? vendor.phone ?? "None found"}
              </span>
            </Figure>
          </dl>

          {/* Unanswered Missing Fields */}
          {vendor.missing_fields.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              <span className="font-semibold text-amber-900">Pending Clarification: </span>
              {vendor.missing_fields.map((field) => field.replace(/_/g, " ")).join(", ")}
            </div>
          )}

          {/* Official Website Link */}
          {vendor.website && (
            <div className="pt-1">
              <a
                href={vendor.website}
                target="_blank"
                rel="noreferrer noopener"
                className="btn btn-quiet text-xs font-medium text-blue-600 hover:text-blue-800"
              >
                Visit Supplier Website ↗
              </a>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function groupByClassification(
  relationships: Vendor["brand_relationships"],
): [string, Vendor["brand_relationships"]][] {
  const rank = [
    "verified",
    "strong_evidence",
    "indirect_evidence",
    "supplier_reported",
    "unverified",
    "no_public_evidence",
  ];
  const groups = new Map<string, Vendor["brand_relationships"]>();
  for (const relationship of relationships) {
    const key = relationship.classification;
    groups.set(key, [...(groups.get(key) ?? []), relationship]);
  }
  return [...groups.entries()].sort(
    ([a], [b]) =>
      (rank.indexOf(a) === -1 ? rank.length : rank.indexOf(a)) -
      (rank.indexOf(b) === -1 ? rank.length : rank.indexOf(b)),
  );
}

function Figure({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className="mt-1">{children}</dd>
    </div>
  );
}


