"use client";

import type { Dimension, Fact, Provenance, Trust } from "@/lib/types";

/*
 * The provenance stamp is this product's signature device. It sits beside every
 * asserted figure and says HOW the figure was obtained — never whether the
 * figure is good news. A confirmed MOQ of 5,000 and a confirmed MOQ of 500 wear
 * the same stamp; only the source differs.
 */

const PROVENANCE: Record<Provenance, { label: string; className: string; hint: string }> = {
  verified: {
    label: "verified",
    className: "bg-petrol-light text-petrol-deep",
    hint: "two or more independent sources agree",
  },
  direct_quote: {
    label: "direct",
    className: "bg-petrol-light text-petrol-deep",
    hint: "the supplier told us, in writing or on a recorded call",
  },
  publicly_listed: {
    label: "published",
    className: "bg-slate2-light text-muted",
    hint: "stated on a public page",
  },
  supplier_reported: {
    label: "supplier says",
    className: "bg-amber-light text-amber",
    hint: "the supplier's own claim, with nothing corroborating it",
  },
  estimated: {
    label: "estimated",
    className: "bg-amber-light text-amber",
    hint: "approximated, not stated",
  },
  inferred: {
    label: "inferred",
    className: "bg-amber-light text-amber",
    hint: "derived, not stated by any source",
  },
  conflicting: {
    label: "sources differ",
    className: "bg-rose-light text-rose",
    hint: "sources disagree and it is not settled",
  },
  unknown: {
    label: "unknown",
    className: "bg-slate2-light text-faint",
    hint: "nobody has told us",
  },
};

export function ProvenanceStamp({ provenance }: { provenance: Provenance }) {
  const style = PROVENANCE[provenance] ?? PROVENANCE.unknown;
  return (
    <span
      title={style.hint}
      className={`inline-flex items-center rounded-sm px-1.5 py-0.5 font-mono text-2xs
                  uppercase tracking-[0.08em] ${style.className}`}
    >
      {style.label}
    </span>
  );
}

/**
 * A segmented meter, not a progress bar. Ten discrete cells read as a
 * measurement taken off an instrument rather than progress toward a finish
 * line — which is the honest reading, because confidence is a level, not a
 * task that completes.
 */
export function ConfidenceMeter({ value, tone = "petrol" }: { value: number; tone?: string }) {
  const filled = Math.round(Math.max(0, Math.min(1, value)) * 10);
  const fill = tone === "rose" ? "bg-rose" : tone === "amber" ? "bg-amber" : "bg-petrol";
  return (
    <span className="inline-flex gap-[2px] align-middle" aria-hidden>
      {Array.from({ length: 10 }, (_, index) => (
        <span
          key={index}
          className={`h-3 w-[3px] rounded-[1px] ${index < filled ? fill : "bg-rule"}`}
        />
      ))}
    </span>
  );
}

export function TrustBreakdown({ trust }: { trust: Trust }) {
  return (
    <dl className="space-y-1.5">
      {trust.dimensions.map((dimension: Dimension) => (
        <div key={dimension.name} className="flex items-baseline gap-3">
          <dt className="col-label w-28 shrink-0">{dimension.name.replace(/_/g, " ")}</dt>
          <dd className="flex min-w-0 flex-1 items-center gap-2">
            <ConfidenceMeter
              value={dimension.score}
              tone={dimension.score >= 0.6 ? "petrol" : dimension.score >= 0.3 ? "amber" : "rose"}
            />
            <span className="figure w-9 text-right text-xs">
              {Math.round(dimension.score * 100)}%
            </span>
            <span className="truncate text-xs text-muted">{dimension.explanation}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** A figure plus its stamp. Clicking it opens the sources behind it. */
export function SourcedFigure({
  fact,
  format,
  unknownLabel = "not yet known",
  onOpen,
}: {
  fact: Fact;
  format?: (value: string | number) => string;
  unknownLabel?: string;
  onOpen?: (evidenceIds: string[], label: string) => void;
}) {
  const known = fact.value !== null && fact.provenance !== "unknown";
  if (!known) {
    return <span className="font-mono text-xs text-faint">{unknownLabel}</span>;
  }
  const rendered = format ? format(fact.value as string | number) : String(fact.value);
  const clickable = Boolean(onOpen) && fact.evidence_ids.length > 0;
  return (
    <span className="inline-flex items-baseline gap-2">
      <span
        className={`figure text-sm ${clickable ? "sourced" : ""}`}
        onClick={clickable ? () => onOpen!(fact.evidence_ids, rendered) : undefined}
        role={clickable ? "button" : undefined}
        tabIndex={clickable ? 0 : undefined}
        onKeyDown={
          clickable
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onOpen!(fact.evidence_ids, rendered);
                }
              }
            : undefined
        }
      >
        {rendered}
      </span>
      <ProvenanceStamp provenance={fact.provenance} />
    </span>
  );
}

const STATUS_TONE: Record<string, string> = {
  qualified: "bg-petrol-light text-petrol-deep",
  completed: "bg-petrol-light text-petrol-deep",
  responded: "bg-petrol-light text-petrol-deep",
  rejected: "bg-slate2-light text-muted",
  failed: "bg-rose-light text-rose",
  contacted: "bg-amber-light text-amber",
  sent: "bg-amber-light text-amber",
  awaiting_approval: "bg-rose-light text-rose",
  awaiting_response: "bg-amber-light text-amber",
  not_attempted: "bg-slate2-light text-muted",
};

export function StatusChip({ status, live = false }: { status: string; live?: boolean }) {
  const tone = STATUS_TONE[status] ?? "bg-slate2-light text-muted";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 font-mono
                  text-2xs uppercase tracking-[0.08em] ${tone}`}
    >
      {live && <span className="h-1.5 w-1.5 rounded-full bg-current animate-breathe" />}
      {status.replace(/_/g, " ")}
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
  return Number.isNaN(days) ? String(value) : `${days} days`;
}

export function formatUnits(value: number | string): string {
  const units = typeof value === "number" ? value : Number(value);
  return Number.isNaN(units) ? String(value) : units.toLocaleString("en-US");
}
