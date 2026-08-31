"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, TERMINAL_STATUSES } from "@/lib/api";
import { StatusChip } from "@/components/primitives";
import type { Mission, SearchScope } from "@/lib/types";

const SCOPES: { value: SearchScope; label: string; hint: string; icon: string }[] = [
  // Labelled with the same three words the API, the docs and `SearchScope` use.
  // "Metro / Domestic / Cross-border" was a second vocabulary for the same
  // choice, and the longest of them could not fit a phone without truncating.
  {
    value: "city",
    label: "City",
    hint: "Only suppliers in or around the city you name.",
    icon: "📍",
  },
  {
    value: "country",
    label: "Country",
    hint: "Anywhere inside the country you name.",
    icon: "🏭",
  },
  {
    value: "global",
    label: "Global",
    hint: "Anywhere in the world. Importing is assumed, so distance is not penalised.",
    icon: "🌐",
  },
];

export default function MissionsPage() {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [loading, setLoading] = useState(true);
  const [objective, setObjective] = useState("");
  const [scope, setScope] = useState<SearchScope>("country");
  const [location, setLocation] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .missions()
      .then(setMissions)
      .catch(() => setError("Could not reach the API. If you are running this locally, start the backend first."))
      .finally(() => setLoading(false));
  }, []);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const mission = await api.createMission(objective, { location, scope });
      window.location.href = `/missions/${mission.id}`;
    } catch {
      setError("The mission could not be started. The API did not accept it — try again.");
      setStarting(false);
    }
  }

  const activeScope = SCOPES.find((option) => option.value === scope)!;
  const blocked =
    objective.trim().length < 10 || (scope !== "global" && location.trim().length === 0);

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900 lg:h-screen lg:overflow-hidden">
      <header className="z-30 shrink-0 border-b border-slate-200 bg-white shadow-xs">
        <div className="mx-auto flex h-14 w-full max-w-[1440px] items-center justify-between px-5 sm:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <Link href="/" className="flex shrink-0 items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-sm font-bold text-white">
                S
              </span>
              <span className="font-display text-base font-bold tracking-tight text-slate-900">
                SupplyMe
              </span>
            </Link>
            <span aria-hidden className="hidden h-4 w-px shrink-0 bg-slate-200 sm:block" />
            <span className="hidden truncate text-sm text-slate-500 sm:block">
              Autonomous supplier discovery
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1440px] flex-1 px-5 py-7 sm:px-8 sm:py-9 lg:min-h-0 lg:overflow-hidden">
        <div className="grid gap-8 lg:h-full lg:min-h-0 lg:grid-cols-12 lg:gap-10">
          {/* Composer */}
          <div className="flex min-w-0 flex-col gap-6 lg:col-span-7 lg:min-h-0 lg:overflow-y-auto lg:pr-1 xl:col-span-8 scroll-thin">
            <section className="max-w-2xl">
              <h1 className="font-display text-3xl font-bold leading-[1.12] tracking-tight text-slate-900 sm:text-[2.5rem]">
                Say what you want to make.
              </h1>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-subtle sm:p-7">
              <div>
                <label htmlFor="objective" className="font-display text-base font-semibold text-slate-900">
                  What are you producing?
                </label>
                <p className="mt-1 text-sm text-slate-500">
                  Any physical product. Include the unit count, the specification, and anything
                  you need to keep low-risk — the supply chain is worked out from what you write.
                </p>
              </div>

              <textarea
                id="objective"
                value={objective}
                onChange={(event) => setObjective(event.target.value)}
                rows={4}
                className="field mt-4 min-h-[7.5rem] resize-y bg-slate-50 leading-relaxed focus:bg-white"
                placeholder="What you are making, how many, where, and what matters most."
              />

              <fieldset className="mt-6 border-t border-slate-100 pt-5">
                <legend className="sr-only">Where to search</legend>
                <p className="text-sm font-semibold text-slate-800">Where should we look?</p>

                <div className="mt-3 flex min-w-0 flex-col gap-3 sm:flex-row sm:items-stretch">
                  {/* Three equal columns on a phone, so the segmented control
                      fits the width instead of setting it. */}
                  <div
                    role="group"
                    aria-label="Search scope"
                    className="grid w-full grid-cols-3 rounded-xl border border-slate-200 bg-slate-100 p-1 sm:inline-flex sm:w-auto sm:shrink-0"
                  >
                    {SCOPES.map((option) => {
                      const active = scope === option.value;
                      return (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => setScope(option.value)}
                          aria-pressed={active}
                          className={`flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-semibold transition-colors sm:flex-none sm:px-3.5 ${
                            active
                              ? "bg-white text-slate-900 shadow-xs"
                              : "text-slate-600 hover:text-slate-900"
                          }`}
                        >
                          <span aria-hidden>{option.icon}</span>
                          <span className="truncate">{option.label}</span>
                        </button>
                      );
                    })}
                  </div>

                  <input
                    id="location"
                    value={scope === "global" ? "" : location}
                    onChange={(event) => setLocation(event.target.value)}
                    disabled={scope === "global"}
                    aria-label={scope === "city" ? "City" : "Country"}
                    placeholder={scope === "city" ? "Los Angeles" : scope === "global" ? "Worldwide" : "United States"}
                    className="field flex-1 text-sm sm:max-w-[16rem]"
                  />
                </div>

                <p className="mt-2.5 min-h-[1.75rem] text-xs leading-relaxed text-slate-500">
                  {activeScope.hint}
                </p>
              </fieldset>

              <div className="mt-5 flex flex-col gap-4 border-t border-slate-100 pt-5 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-xs text-slate-500">
                  Discovery, outreach, and verification run on their own once you start.
                </p>
                <button
                  onClick={start}
                  disabled={starting || blocked}
                  className="btn btn-primary w-full px-6 py-2.5 text-sm font-semibold sm:w-auto"
                >
                  {starting ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                      <span>Starting…</span>
                    </>
                  ) : (
                    <>
                      <span>Start sourcing</span>
                      <span aria-hidden className="text-base">→</span>
                    </>
                  )}
                </button>
              </div>

              {error && (
                <p
                  role="alert"
                  className="mt-5 rounded-lg border border-rose-200 bg-rose-50 p-4 text-xs font-medium leading-relaxed text-rose-800"
                >
                  {error}
                </p>
              )}
            </section>
          </div>

          {/* Mission rail */}
          {/* min-w-0 because a grid item defaults to min-width:auto: without it
              the rail's min-content width set the column's, and the page
              scrolled sideways on a phone rather than the objective wrapping. */}
          <aside className="flex min-h-0 min-w-0 flex-col lg:col-span-5 xl:col-span-4">
            <div className="flex shrink-0 items-baseline justify-between gap-3 border-b border-slate-200 pb-3">
              <h2 className="font-display text-base font-semibold text-slate-900">Missions</h2>
              <span className="font-mono text-xs font-semibold text-slate-500">
                {loading ? "—" : `${missions.length} total`}
              </span>
            </div>

            <div className="relative mt-4 flex-1 lg:min-h-0">
              <div className="space-y-3 lg:h-full lg:overflow-y-auto lg:pb-10 lg:pr-1 scroll-thin">
                {loading ? (
                  [0, 1, 2].map((i) => (
                    <div
                      key={i}
                      className="h-[104px] animate-pulse rounded-xl border border-slate-200 bg-white"
                    />
                  ))
                ) : missions.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center">
                    <p className="text-sm font-medium text-slate-700">No missions yet</p>
                    <p className="mt-1 text-xs leading-relaxed text-slate-500">
                      Describe what you want to make, then start sourcing. Runs show up here.
                    </p>
                  </div>
                ) : (
                  missions.map((mission) => (
                    <Link
                      key={mission.id}
                      href={`/missions/${mission.id}`}
                      className="group block rounded-xl border border-slate-200 bg-white p-4 shadow-subtle transition-all hover:border-slate-300 hover:shadow-card"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-1.5">
                          <span className="shrink-0 font-mono text-xs font-semibold text-slate-400">
                            #{mission.id.slice(0, 8)}
                          </span>
                          {mission.product && (
                            <span className="min-w-0 truncate rounded border border-slate-200 bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-700">
                              {mission.product}
                            </span>
                          )}
                          {mission.quantity && (
                            <span className="shrink-0 rounded border border-slate-200 bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600">
                              {mission.quantity.toLocaleString()} u
                            </span>
                          )}
                        </div>
                        <StatusChip
                          status={mission.status}
                          live={!TERMINAL_STATUSES.has(mission.status)}
                        />
                      </div>

                      <p className="clamp-2 mt-2.5 text-sm font-medium leading-relaxed text-slate-900 transition-colors group-hover:text-blue-700">
                        {mission.objective}
                      </p>

                      <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2.5 text-xs text-slate-500">
                        <span className="flex items-center gap-2">
                          <span>{mission.market ?? "Market not set"}</span>
                          <span className="text-slate-300">·</span>
                          <span>{mission.emails_sent} sent</span>
                        </span>
                        <span className="font-semibold text-slate-400 transition-colors group-hover:text-blue-700">
                          Open →
                        </span>
                      </div>
                    </Link>
                  ))
                )}
              </div>
              <div
                aria-hidden
                className="pointer-events-none absolute inset-x-0 bottom-0 hidden h-10 bg-gradient-to-t from-slate-50 to-transparent lg:block"
              />
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
