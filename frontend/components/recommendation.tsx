"use client";

import type { Recommendation, Selection } from "@/lib/types";
import { ConfidenceMeter } from "./primitives";

/*
 * The ranking arrives already computed and already explained — the scoring
 * engine produced one sentence per component. This panel shows those sentences
 * rather than a bar chart, because "MOQ 500 fits an order of 500" tells a buyer
 * something a bar cannot.
 */
export function RecommendationPanel({
  recommendation,
  live,
  currencyFormat,
}: {
  recommendation: Recommendation | null;
  live: boolean;
  currencyFormat: (value: number) => string;
}) {
  if (!recommendation) {
    return (
      <p className="py-8 text-sm text-muted">
        {live
          ? "The ranking is computed once every supplier has been settled either way."
          : "No ranking was produced for this mission."}
      </p>
    );
  }

  return (
    <div className="space-y-8">
      <section>
        <h3 className="col-label mb-3">Recommended supply network</h3>
        <div className="space-y-3">
          {recommendation.selections.map((selection) => (
            <SelectionCard
              key={`${selection.node_key}-${selection.vendor.id}`}
              selection={selection}
              currencyFormat={currencyFormat}
            />
          ))}
        </div>
        {recommendation.estimated_unit_cost !== null && (
          <p className="mt-4 flex items-baseline justify-between border-t border-rule pt-3">
            <span className="col-label">Components priced so far, per unit</span>
            <span className="figure text-lg">
              {currencyFormat(recommendation.estimated_unit_cost)}
            </span>
          </p>
        )}
      </section>

      {recommendation.rejected.length > 0 && (
        <section>
          <h3 className="col-label mb-1">Not viable, and why</h3>
          <p className="mb-3 text-xs text-muted">
            A supplier ruled out here may be an excellent supplier at a different scale.
          </p>
          <ul className="divide-y divide-rule border-y border-rule">
            {recommendation.rejected.map((row, index) => (
              <li key={index} className="flex items-baseline justify-between gap-6 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm text-ink">{row.vendor.name}</p>
                  <p className="col-label mt-0.5">{row.node_name}</p>
                </div>
                <p className="max-w-md text-right text-xs text-muted">
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

      <div className="grid gap-6 sm:grid-cols-3">
        <Column title="Risks" items={recommendation.risks} />
        <Column title="Still unknown" items={recommendation.unknowns} />
        <Column title="Do these next" items={recommendation.next_actions} ordered />
      </div>
    </div>
  );
}

function SelectionCard({
  selection,
  currencyFormat,
}: {
  selection: Selection;
  currencyFormat: (value: number) => string;
}) {
  return (
    <article className="card p-5">
      <header className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          <p className="col-label">{selection.node_name}</p>
          <h4 className="mt-1 truncate text-base font-medium text-ink">
            {selection.vendor.name}
          </h4>
          <p className="mt-0.5 font-mono text-2xs uppercase tracking-[0.08em] text-faint">
            {[selection.vendor.city, selection.vendor.country].filter(Boolean).join(", ")}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="figure text-2xl">{selection.score.total.toFixed(0)}</p>
          <p className="col-label">out of 100</p>
        </div>
      </header>

      {selection.quote?.unit_price != null && (
        <p className="mt-3 flex items-baseline gap-2">
          <span className="figure text-sm">{currencyFormat(selection.quote.unit_price)}</span>
          <span className="text-xs text-muted">
            per unit{selection.quote.bundled ? ", quoted as a bundle" : ""}
          </span>
        </p>
      )}

      <ul className="mt-4 space-y-1.5">
        {(selection.why ?? []).map((reason, index) => (
          <li key={index} className="flex gap-2 text-sm text-muted">
            <span className="text-petrol">·</span>
            <span>{reason}</span>
          </li>
        ))}
      </ul>

      <details className="mt-4 border-t border-rule pt-3">
        <summary className="col-label cursor-pointer hover:text-petrol">
          How the score was reached
        </summary>
        <ul className="mt-3 space-y-2">
          {selection.score.components.map((component) => (
            <li key={component.name} className="flex items-baseline gap-3">
              <span className="col-label w-20 shrink-0">{component.name.replace(/_/g, " ")}</span>
              <ConfidenceMeter value={component.raw} />
              <span className="figure w-12 shrink-0 text-right text-xs">
                {(component.contribution * 100).toFixed(1)}
              </span>
              <span className="min-w-0 flex-1 text-xs text-muted">{component.explanation}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-2xs text-faint">
          Each row is weight × fit. The weights come from what you said mattered.
        </p>
      </details>
    </article>
  );
}

function Column({
  title,
  items,
  ordered = false,
}: {
  title: string;
  items: string[];
  ordered?: boolean;
}) {
  if (items.length === 0) return null;
  const List = ordered ? "ol" : "ul";
  return (
    <section>
      <h3 className="col-label mb-2">{title}</h3>
      <List className="space-y-1.5">
        {items.map((item, index) => (
          <li key={index} className="flex gap-2 text-xs leading-relaxed text-muted">
            <span className="figure shrink-0 text-faint">
              {ordered ? `${index + 1}.` : "·"}
            </span>
            <span>{item}</span>
          </li>
        ))}
      </List>
    </section>
  );
}
