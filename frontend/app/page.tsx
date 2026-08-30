"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { StatusChip } from "@/components/primitives";
import type { Mission, SearchScope } from "@/lib/types";

const SCOPES: { value: SearchScope; label: string; hint: string }[] = [
  { value: "city", label: "Near a city", hint: "Only suppliers in or around the city you name." },
  { value: "country", label: "Country", hint: "Anywhere in the country you name." },
  { value: "global", label: "Anywhere", hint: "No geographic limit; importing is expected." },
];

const EXAMPLE =
  "I want to launch a 50ml EDP perfume in Indonesia. Initial production: 500 units. " +
  "I want premium packaging, but I want to minimize risk on the first batch. " +
  "Find the suppliers I need, research them, and contact the best candidates.";

export default function MissionsPage() {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [objective, setObjective] = useState(EXAMPLE);
  const [scope, setScope] = useState<SearchScope>("country");
  const [location, setLocation] = useState("Indonesia");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<{ providers: Record<string, string>; notes: string[] } | null>(null);

  useEffect(() => {
    api.missions().then(setMissions).catch(() => setError("Cannot reach the API."));
    api.health().then(setHealth).catch(() => {});
  }, []);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const mission = await api.createMission(objective, { location, scope });
      window.location.href = `/missions/${mission.id}`;
    } catch {
      setError("Could not start the mission. Check the API is running.");
      setStarting(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-16">
      <header className="mb-12">
        <p className="col-label">VendorDiscoveryShortcut</p>
        <h1 className="mt-3 max-w-2xl font-serif text-4xl leading-tight text-ink">
          Tell it what you want to make.
          <br />
          It finds the suppliers, and shows its sources.
        </h1>
        <p className="mt-4 max-w-xl text-sm leading-relaxed text-muted">
          It works out which suppliers a product needs, searches for them, reads what they
          publish, emails them, follows up until a question is settled, and reports what
          it could and could not establish.
        </p>
      </header>

      <section className="card p-6">
        <label htmlFor="objective" className="col-label">
          What are you making?
        </label>
        <textarea
          id="objective"
          value={objective}
          onChange={(event) => setObjective(event.target.value)}
          rows={4}
          className="mt-3 w-full resize-y rounded-md border border-rule bg-paper/40 px-4 py-3
                     font-serif text-base leading-relaxed text-ink placeholder:text-faint
                     focus:border-petrol focus:outline-none"
          placeholder="Describe the product, the quantity, the market, and what matters to you."
        />
        <fieldset className="mt-6 border-t border-rule pt-5">
          <legend className="sr-only">Where to look</legend>
          <p className="col-label">Where should it look?</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {SCOPES.map((option) => {
              const active = scope === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setScope(option.value)}
                  aria-pressed={active}
                  className={`rounded-md border px-3.5 py-2 font-mono text-2xs uppercase
                              tracking-[0.08em] transition-colors ${
                                active
                                  ? "border-petrol bg-petrol-light/50 text-petrol-deep"
                                  : "border-rule text-muted hover:border-petrol/50"
                              }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-3">
            <input
              id="location"
              value={location}
              onChange={(event) => setLocation(event.target.value)}
              disabled={scope === "global"}
              aria-label={scope === "city" ? "City" : "Country"}
              placeholder={scope === "city" ? "Surabaya" : "Indonesia"}
              className="w-52 rounded-md border border-rule bg-paper/40 px-3 py-2 font-serif
                         text-sm text-ink placeholder:text-faint focus:border-petrol
                         focus:outline-none disabled:cursor-not-allowed disabled:text-faint"
            />
            <p className="text-xs text-muted">
              {SCOPES.find((option) => option.value === scope)?.hint}
            </p>
          </div>
        </fieldset>

        <div className="mt-5 flex items-center justify-between gap-4">
          <p className="text-xs text-muted">
            Say the quantity if you know it. It will not invent one.
          </p>
          <button
            onClick={start}
            disabled={
              starting ||
              objective.trim().length < 10 ||
              (scope !== "global" && location.trim().length === 0)
            }
            className="shrink-0 rounded-md bg-petrol px-5 py-2.5 font-mono text-2xs uppercase
                       tracking-[0.1em] text-white transition-colors hover:bg-petrol-deep
                       disabled:cursor-not-allowed disabled:bg-faint"
          >
            {starting ? "Starting…" : "Start sourcing"}
          </button>
        </div>
        {error && <p className="mt-3 text-sm text-rose">{error}</p>}
      </section>

      {health && (
        <p className="mt-4 font-mono text-2xs uppercase tracking-[0.08em] text-faint">
          {health.providers.llm} · {health.providers.mail}
          {health.notes.length > 0 && ` · ${health.notes[0]}`}
        </p>
      )}

      <section className="mt-14">
        <h2 className="col-label mb-3">Missions</h2>
        {missions.length === 0 ? (
          <p className="py-8 text-sm text-muted">
            No missions yet. Describe a product above to start one.
          </p>
        ) : (
          <ul className="divide-y divide-rule border-y border-rule">
            {missions.map((mission) => (
              <li key={mission.id}>
                <Link
                  href={`/missions/${mission.id}`}
                  className="flex items-start justify-between gap-6 py-4 hover:bg-surface/60"
                >
                  <div className="min-w-0">
                    <p className="truncate font-serif text-base text-ink">{mission.objective}</p>
                    <p className="mt-1 font-mono text-2xs uppercase tracking-[0.08em] text-faint">
                      {mission.id} · {mission.emails_sent} emails
                    </p>
                  </div>
                  <StatusChip
                    status={mission.status}
                    live={!["completed", "failed"].includes(mission.status)}
                  />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
