"use client";

import type { Recommendation, Selection } from "@/lib/types";
import { ConfidenceMeter, formatMoney, humanLabel } from "./primitives";

/*
 * The finished report: which supplier was chosen for each component line, why,
 * and what the mission never managed to establish.
 *
 * The ranking is computed in app/domain/scoring.py before the narrative agent
 * ever runs, and the agent may not reorder it — so every score shown here is
 * arithmetic the "how the score was reached" panel can reproduce line by line.
 */

export function RecommendationPanel({
  recommendation,
  live,
}: {
  recommendation: Recommendation | null;
  live: boolean;
}) {
  if (!recommendation) {
    return (
      <div className="card p-12 text-center border-dashed bg-white">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-purple-50 text-purple-600 font-bold">
          ⚖
        </div>
        <p className="text-base font-semibold text-slate-800">
          {live ? "Synthesizing Supply Network Ranking" : "No Recommendation Produced"}
        </p>
        <p className="mx-auto mt-1.5 max-w-md text-xs leading-relaxed text-slate-500">
          {live
            ? "Ranking runs by itself once every supplier has either been qualified or ruled out."
            : "This mission ended before there was anything to rank."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Executive Procurement Narrative Card */}
      {recommendation.narrative && (
        <section className="card p-6 border-blue-200 bg-blue-50/30">
          <div className="flex items-center gap-2 pb-2 mb-2 border-b border-blue-100">
            <span className="h-2 w-2 rounded-full bg-blue-600" />
            <h2 className="text-xs font-semibold uppercase tracking-wider text-blue-700">
              Summary
            </h2>
          </div>
          <p className="text-sm leading-relaxed text-slate-800 sm:text-base">
            {recommendation.narrative}
          </p>
        </section>
      )}

      {/* Selected Supply Network */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4 pb-3 border-b border-slate-200">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Recommended Supply Network ({recommendation.selections.length} Selected)
            </h2>
            <p className="text-xs text-slate-500">
              Top-ranked suppliers weighted by your priority parameters
            </p>
          </div>

          {recommendation.estimated_unit_cost !== null && (
            <div className="rounded-lg bg-emerald-50 px-3.5 py-1.5 border border-emerald-200">
              <div className="flex items-baseline gap-2">
                <span className="text-xs font-medium text-emerald-800">
                  Quoted so far, per unit:
                </span>
                <span className="text-base font-bold text-emerald-800 font-mono">
                  {formatMoney(recommendation.estimated_unit_cost, recommendation.currency)}
                </span>
              </div>
              {/* A sum over some of the components is not the unit cost of the
                  product. Saying which is which is the difference between a
                  figure and a claim. */}
              <p className="mt-0.5 text-xs text-emerald-900/70">
                {priced(recommendation)} of {recommendation.selections.length} selected
                {" "}
                {recommendation.selections.length === 1 ? "component" : "components"} priced
              </p>
            </div>
          )}
        </div>

        <div className="space-y-3">
          {recommendation.selections.map((selection) => (
            <SelectionCard
              key={`${selection.node_key}-${selection.vendor.id}`}
              selection={selection}
            />
          ))}
        </div>
      </section>

      {/* Disqualified Candidates Ledger */}
      {recommendation.rejected.length > 0 && (
        <section className="card p-5 border-slate-200 bg-white space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-rose-600 text-sm font-bold">✕</span>
            <h3 className="text-sm font-semibold text-slate-800">
              Disqualified Candidates ({recommendation.rejected.length})
            </h3>
          </div>
          <p className="text-xs text-slate-500">
Ruled out for this batch — usually a minimum order far above what is being bought, or no way to contact them. The reason is on each row.
          </p>

          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-slate-50/50 overflow-hidden">
            {recommendation.rejected.map((row, index) => (
              <li
                key={index}
                className="flex flex-col gap-1.5 p-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
              >
                <div className="min-w-0">
                  <p className="font-semibold text-slate-800 text-xs">{row.vendor.name}</p>
                  <p className="text-xs text-slate-500">{row.node_name}</p>
                </div>
                <p className="text-xs text-rose-700 sm:max-w-md sm:text-right font-medium">
                  {(row.score.rejection_reasons.length > 0
                    ? row.score.rejection_reasons
                    : row.vendor.rejection_reasons
                  ).join("; ")}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Tactical 3-Column Triage Board */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Column
          title="Operational Risks"
          subtitle="Variables requiring mitigation"
          items={recommendation.risks}
          accent="amber"
          icon="⚠"
        />
        <Column
          title="Unsettled Unknowns"
          subtitle="Information yet to be confirmed"
          items={recommendation.unknowns}
          accent="purple"
          icon="?"
        />
        <Column
          title="Immediate Next Steps"
          subtitle="Tactical buyer checklist"
          items={recommendation.next_actions}
          accent="emerald"
          icon="✓"
          ordered
        />
      </div>
    </div>
  );
}

/** How many selections the headline total actually covers. */
function priced(recommendation: Recommendation): number {
  return (
    recommendation.priced_selections ??
    recommendation.selections.filter((s) => s.quote?.unit_price != null).length
  );
}

function SelectionCard({ selection }: { selection: Selection }) {
  const place = [selection.vendor.city, selection.vendor.country].filter(Boolean).join(", ");
  const scoreTotal = Math.round(selection.score.total);

  return (
    <article className="card p-5 border-emerald-300 ring-1 ring-emerald-200 bg-white transition-all">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700 border border-slate-200">
              {selection.node_name}
            </span>
          </div>
          <h3 className="mt-1.5 text-base font-semibold text-slate-900">
            {selection.vendor.name}
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            {place || "Location unverified"}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {selection.quote?.unit_price != null && (
            <div className="text-right">
              <span className="text-xs text-slate-500 block">Unit Quote</span>
              {/* This quote's own currency, not the report's. A supplier who
                  quoted IDR must not be rendered in USD because the mission's
                  market implied one. */}
              <span className="text-base font-bold text-slate-900 font-mono">
                {formatMoney(selection.quote.unit_price, selection.quote.currency)}
              </span>
            </div>
          )}

          <div className="flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800">
            <span className="text-sm font-bold font-mono leading-none">
              {scoreTotal}
            </span>
            <span className="text-[0.6rem] font-medium text-emerald-600">/ 100</span>
          </div>
        </div>
      </header>

      {/* Rationale Bullet Points */}
      {(selection.why ?? []).length > 0 && (
        <ul className="mt-4 space-y-1.5 rounded-lg bg-slate-50 p-3 border border-slate-200/80">
          {(selection.why ?? []).map((reason, index) => (
            <li key={index} className="flex items-start gap-2 text-xs text-slate-700 leading-relaxed">
              <span className="text-emerald-600 font-bold">✓</span>
              <span>{reason}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Score Components Accordion */}
      <details className="mt-3 border-t border-slate-100 pt-2.5">
        <summary className="cursor-pointer text-xs font-semibold text-blue-600 hover:text-blue-800">
          ▶ How the score was reached
        </summary>
        <div className="mt-2.5 space-y-2 rounded-lg bg-slate-50 p-3 border border-slate-200">
          <ul className="space-y-2">
            {selection.score.components.map((component) => (
              <li
                key={component.name}
                className="grid grid-cols-[7rem_auto_3rem_1fr] items-center gap-x-3 gap-y-1 max-sm:grid-cols-[1fr_auto] max-sm:gap-y-1"
              >
                <span className="text-xs font-medium text-slate-700 truncate max-sm:col-span-2">
                  {humanLabel(component.name)}
                </span>
                <ConfidenceMeter value={component.raw} tone="blue" />
                <span className="font-mono text-right text-xs font-bold text-slate-800">
                  {(component.contribution * 100).toFixed(1)}
                </span>
                <span className="truncate text-xs text-slate-500 max-sm:col-span-2">
                  {component.explanation}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </details>
    </article>
  );
}

function Column({
  title,
  subtitle,
  items,
  ordered = false,
  accent = "blue",
  icon = "•",
}: {
  title: string;
  subtitle: string;
  items: string[];
  ordered?: boolean;
  accent?: "amber" | "purple" | "emerald" | "blue";
  icon?: string;
}) {
  if (items.length === 0) return null;

  const accentStyles = {
    amber: "border-amber-200 bg-amber-50/40 text-amber-900",
    purple: "border-purple-200 bg-purple-50/40 text-purple-900",
    emerald: "border-emerald-200 bg-emerald-50/40 text-emerald-900",
    blue: "border-blue-200 bg-blue-50/40 text-blue-900",
  }[accent];

  const List = ordered ? "ol" : "ul";

  return (
    <section className={`card p-5 ${accentStyles}`}>
      <div className="flex items-center justify-between pb-2 mb-2 border-b border-black/5">
        <div>
          <h3 className="text-sm font-bold text-slate-900">{title}</h3>
          <p className="text-xs text-slate-500">{subtitle}</p>
        </div>
        <span className="text-xs font-semibold px-2 py-0.5 rounded bg-white border border-slate-200 text-slate-700 font-mono">
          {items.length}
        </span>
      </div>

      <List className="space-y-1.5 mt-2.5">
        {items.map((item, index) => (
          <li key={index} className="flex items-start gap-2 text-xs leading-relaxed text-slate-700">
            <span className="font-mono font-bold text-slate-400 shrink-0">
              {ordered ? `${index + 1}.` : icon}
            </span>
            <span>{item}</span>
          </li>
        ))}
      </List>
    </section>
  );
}


