"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

import { ActivityFeed } from "@/components/activity";
import { EvidenceDrawer } from "@/components/evidence-drawer";
import { StatusChip, formatMoney } from "@/components/primitives";
import { VendorCard } from "@/components/vendor-card";
import { api } from "@/lib/api";
import type {
  ActivityEntry, Approval, Evidence, Mission, MissionCounts,
  Recommendation, SupplyChainNode, Vendor,
} from "@/lib/types";
import { Communications } from "@/components/communications";
import { RecommendationPanel } from "@/components/recommendation";
import { SupplyChain } from "@/components/supply-chain";

const TABS = [
  { id: "Bill of materials", label: "Bill of Materials", icon: "▥" },
  { id: "Suppliers", label: "Supplier Dossiers", icon: "🏢" },
  { id: "Emails", label: "Communications", icon: "✉" },
  { id: "Recommendation", label: "Strategic Ranking", icon: "★" },
] as const;

type Tab = (typeof TABS)[number]["id"];

const TERMINAL = new Set(["completed", "failed"]);

type VendorFilter = "in_play" | "qualified" | "ruled_out" | "all";

const VENDOR_FILTERS: { value: VendorFilter; label: string }[] = [
  { value: "all", label: "All Candidates" },
  { value: "qualified", label: "Qualified" },
  { value: "in_play", label: "In Pipeline" },
  { value: "ruled_out", label: "Ruled Out" },
];

function matchesFilter(vendor: Vendor, filter: VendorFilter): boolean {
  if (filter === "all") return true;
  if (filter === "qualified") return vendor.status === "qualified";
  if (filter === "ruled_out") return vendor.status === "rejected";
  return vendor.status !== "rejected";
}

const STAGE_RANK: Record<string, number> = {
  qualified: 6,
  responded: 5,
  contacted: 4,
  shortlisted: 3,
  researching: 2,
  discovered: 1,
  rejected: 0,
};

export default function MissionConsole() {
  const { id } = useParams<{ id: string }>();
  const [mission, setMission] = useState<Mission | null>(null);
  const [counts, setCounts] = useState<MissionCounts | null>(null);
  const [nodes, setNodes] = useState<SupplyChainNode[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [communications, setCommunications] = useState<Awaited<
    ReturnType<typeof api.communications>
  > | null>(null);

  const [loadError, setLoadError] = useState<{ status?: number } | null>(null);
  const [decideError, setDecideError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("Bill of materials");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<{ title: string; records: Evidence[] } | null>(null);
  const [logOpen, setLogOpen] = useState(false);
  const [vendorFilter, setVendorFilter] = useState<VendorFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");

  const refresh = useCallback(async () => {
    if (!id) return;
    setLoadError(null);
    try {
      const [overview, vendorList, activityLog, evidenceList, approvalList, comms] =
        await Promise.all([
          api.mission(id),
          api.vendors(id),
          api.activity(id),
          api.evidence(id),
          api.approvals(id),
          api.communications(id),
        ]);
      setMission(overview.mission);
      setCounts(overview.counts);
      setNodes(overview.supply_chain);
      setVendors(vendorList);
      setActivity(activityLog);
      setEvidence(evidenceList);
      setApprovals(approvalList);
      setCommunications(comms);
      if (TERMINAL.has(overview.mission.status)) {
        try {
          setRecommendation(await api.recommendation(id));
        } catch {
          setRecommendation(null);
        }
      }
    } catch (err: any) {
      setLoadError({ status: err?.status });
    }
  }, [id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!mission || TERMINAL.has(mission.status)) return;
    const timer = setInterval(() => refresh(), 2000);
    return () => clearInterval(timer);
  }, [mission, refresh]);

  useEffect(() => {
    if (!mission) return;
    const name = mission.product ?? mission.objective.slice(0, 30);
    document.title = `${name} | SupplyMe`;
    return () => {
      document.title = "SupplyMe";
    };
  }, [mission]);

  const vendorNames = useMemo(
    () => Object.fromEntries(vendors.map((vendor) => [vendor.id, vendor.name])),
    [vendors],
  );
  const evidenceById = useMemo(
    () => Object.fromEntries(evidence.map((record) => [record.id, record])),
    [evidence],
  );

  const shownVendors = useMemo(() => {
    return vendors
      .filter((vendor) => matchesFilter(vendor, vendorFilter))
      .filter((vendor) => {
        if (!searchQuery.trim()) return true;
        const q = searchQuery.toLowerCase();
        return (
          vendor.name.toLowerCase().includes(q) ||
          vendor.city?.toLowerCase().includes(q) ||
          vendor.country?.toLowerCase().includes(q) ||
          vendor.node_keys.some((k) => k.toLowerCase().includes(q))
        );
      })
      .sort(
        (a, b) =>
          (STAGE_RANK[b.status] ?? 0) - (STAGE_RANK[a.status] ?? 0) ||
          a.name.localeCompare(b.name),
      );
  }, [vendors, vendorFilter, searchQuery]);

  const countFor = useCallback(
    (filter: VendorFilter) =>
      vendors.filter((vendor) => matchesFilter(vendor, filter)).length,
    [vendors],
  );

  const openEvidence = useCallback(
    (ids: string[], label: string) => {
      setDrawer({
        title: label,
        records: ids.map((evidenceId) => evidenceById[evidenceId]).filter(Boolean),
      });
    },
    [evidenceById],
  );

  const pending = approvals.filter((approval) => approval.status === "pending");

  async function decide(approvalId: string, approved: boolean) {
    setDecideError(null);
    try {
      await api.decide(approvalId, approved);
      await refresh();
    } catch (err: any) {
      setDecideError(err?.message ?? "could not reach the API");
    }
  }

  if (!mission || !counts) {
    if (loadError) {
      const gone = loadError.status === 404;
      return (
        <main className="mx-auto max-w-2xl px-6 py-24 text-center">
          <div className="card p-8 bg-white border border-slate-200 rounded-xl">
            <h1 className="text-2xl font-bold text-slate-900">
              {gone ? "Mission not found" : "Could not load this mission"}
            </h1>
            <p className="mt-2 text-xs leading-relaxed text-slate-500">
              {gone
                ? "There is no mission with this id. Missions are only kept between restarts when the API is running against Firestore."
                : "The API did not answer for this mission. Other missions may still open."}
            </p>
            <div className="mt-6">
              <Link href="/" className="btn btn-primary">
                ← Return to Missions Deck
              </Link>
            </div>
          </div>
        </main>
      );
    }
    return (
      <main className="mx-auto max-w-2xl px-6 py-28 text-center">
        <div className="card p-8 flex flex-col items-center justify-center bg-white border border-slate-200 rounded-xl">
          <div className="h-7 w-7 animate-spin rounded-full border-2 border-slate-900 border-t-transparent mb-3" />
          <p className="text-sm font-semibold text-slate-700">Loading Mission Console…</p>
        </div>
      </main>
    );
  }

  const live = !TERMINAL.has(mission.status);
  const context = [
    mission.product,
    mission.quantity ? `${mission.quantity.toLocaleString()} units` : null,
    mission.market,
    mission.unit_spec,
  ].filter(Boolean);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white sticky top-0 z-30 shadow-xs">
        <div className="mx-auto max-w-[1440px] px-5 py-4 sm:px-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <Link
                href="/"
                className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-slate-900 transition-colors"
              >
                <span aria-hidden>←</span> Missions Deck
              </Link>

              <div className="mt-1.5 flex flex-wrap items-center gap-2.5">
                <h1 className="text-lg font-bold text-slate-900 sm:text-xl line-clamp-1">
                  {mission.objective}
                </h1>
              </div>

              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span className="font-mono text-slate-600 font-semibold">#{mission.id}</span>
                {context.map((tag, i) => (
                  <span key={i} className="flex items-center gap-2">
                    <span className="text-slate-300">·</span>
                    <span className="rounded bg-slate-100 px-2 py-0.5 font-medium text-slate-700 border border-slate-200">
                      {tag}
                    </span>
                  </span>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-3">
              <StatusChip status={mission.status} live={live} />
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2.5 border-t border-slate-100 pt-3.5 sm:grid-cols-4 lg:grid-cols-7">
            <ReadoutCard
              label="BOM Lines"
              value={nodes.length}
              icon="▥"
              hint="Required component lines"
            />
            <ReadoutCard
              label="Qualified"
              value={counts.qualified}
              accent={counts.qualified > 0}
              icon="✓"
              hint="Every required fact known, no unresolved disagreement"
            />
            <ReadoutCard
              label="Candidates"
              value={counts.vendors}
              icon="⚑"
              hint="Total discovered suppliers"
            />
            <ReadoutCard
              label="Disqualified"
              value={counts.rejected}
              icon="✕"
              hint="Suppliers ruled out"
            />
            <ReadoutCard
              label="Outreach Replies"
              value={`${counts.emails_responded}/${counts.emails_sent}`}
              hint="Responses received out of sent emails"
              icon="✉"
            />
            <ReadoutCard
              label="Data Conflicts"
              value={counts.open_conflicts}
              alarm={counts.open_conflicts > 0}
              icon="⚡"
              hint="Facts two sources disagree on"
            />
            <ReadoutCard
              label="Evidence Records"
              value={counts.evidence}
              icon="🛡"
              hint="Sources recorded, each with the excerpt it came from"
            />
          </div>
        </div>
      </header>

      {pending.length > 0 && (
        <section className="border-b border-amber-200 bg-amber-50">
          <div className="mx-auto max-w-[1440px] space-y-3 px-5 py-4 sm:px-8">
            <div className="flex items-center gap-2">
              <span className="text-amber-700 font-bold text-base">✋</span>
              <p className="text-xs font-bold text-amber-900 uppercase tracking-wider">
                {pending.length === 1
                  ? "Human Authorization Required: 1 Action Pending"
                  : `Human Authorization Required: ${pending.length} Actions Pending`}
              </p>
            </div>

            {pending.map((approval) => (
              <div
                key={approval.id}
                className="card p-4 border-amber-200 bg-white shadow-subtle flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between rounded-xl"
              >
                <div className="min-w-0 flex-1 space-y-1.5">
                  <p className="text-sm font-semibold text-slate-900">{approval.summary}</p>
                  {approval.preview?.subject && (
                    <p className="font-mono text-xs text-slate-600">
                      Subject: {approval.preview.subject as string}
                    </p>
                  )}
                  {approval.preview?.questions && (
                    <ul className="space-y-1 rounded bg-slate-50 p-2.5 border border-slate-200">
                      <span className="text-xs font-medium text-slate-500 block mb-1">Target Inquiries:</span>
                      {(approval.preview.questions as string[]).map((question, index) => (
                        <li key={index} className="flex gap-2 text-xs text-slate-700">
                          <span className="text-blue-600 font-bold">•</span>
                          <span>{question}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {approval.preview?.body && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-xs font-semibold text-blue-600 hover:text-blue-800">
                        ▶ Read draft correspondence
                      </summary>
                      <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 font-sans text-xs leading-relaxed text-slate-800 border border-slate-200">
                        {approval.preview.body as string}
                      </pre>
                    </details>
                  )}
                </div>

                <div className="flex shrink-0 flex-col items-end gap-1 sm:self-center">
                  <div className="flex gap-2">
                    <button
                      onClick={() => decide(approval.id, true)}
                      className="btn btn-primary px-3.5 py-1.5 text-xs"
                    >
                      Authorize & Send ↗
                    </button>
                    <button
                      onClick={() => decide(approval.id, false)}
                      className="btn btn-quiet px-3.5 py-1.5 text-xs text-rose-700 hover:bg-rose-50"
                    >
                      Hold Back
                    </button>
                  </div>
                  {decideError && <p className="text-xs text-rose-700">{decideError}</p>}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="mx-auto grid max-w-[1440px] gap-6 px-5 py-6 sm:px-8 lg:grid-cols-[minmax(0,1fr)_340px] lg:gap-8">
        <main className="min-w-0 space-y-6">
          <nav
            aria-label="Mission views"
            className="flex items-center gap-1.5 overflow-x-auto rounded-xl bg-slate-100 p-1.5 border border-slate-200"
          >
            {TABS.map((t) => {
              const active = tab === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  aria-current={active ? "page" : undefined}
                  className={`flex shrink-0 items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold transition-all ${
                    active
                      ? "bg-white text-slate-900 shadow-xs"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  <span className="text-sm">{t.icon}</span>
                  <span>{t.label}</span>
                </button>
              );
            })}
          </nav>

          {tab === "Bill of materials" && (
            <SupplyChain nodes={nodes} vendors={vendors} live={live} />
          )}

          {tab === "Suppliers" && (
            <div className="space-y-4">
              {vendors.length === 0 ? (
                <div className="card p-12 text-center border-dashed bg-white">
                  <p className="text-base font-semibold text-slate-800">No Supplier Candidates Yet</p>
                  <p className="mx-auto mt-1.5 max-w-md text-xs leading-relaxed text-slate-500">
                    {live
                      ? "Discovery is searching the open web and Google Places. Suppliers appear as soon as they are identified."
                      : "This mission terminated without discovering suppliers."}
                  </p>
                </div>
              ) : (
                <>
                  <div className="card p-3.5 bg-white border border-slate-200 flex flex-wrap items-center justify-between gap-3 rounded-xl shadow-subtle">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {VENDOR_FILTERS.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => setVendorFilter(option.value)}
                          aria-pressed={vendorFilter === option.value}
                          className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-all ${
                            vendorFilter === option.value
                              ? "bg-slate-900 text-white shadow-xs"
                              : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
                          }`}
                        >
                          {option.label}
                          <span className="ml-1.5 font-mono text-xs opacity-75">
                            ({countFor(option.value)})
                          </span>
                        </button>
                      ))}
                    </div>

                    <div className="w-full sm:w-60">
                      <input
                        type="search"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search suppliers or components…"
                        className="w-full bg-slate-50 border border-slate-200 rounded-lg px-3 py-1.5 text-xs focus:bg-white focus:outline-none focus:border-slate-400"
                      />
                    </div>
                  </div>

                  {shownVendors.length === 0 ? (
                    <div className="card p-8 text-center bg-white border border-slate-200 rounded-xl">
                      <p className="text-xs text-slate-500">
                        No candidates match the active filter criteria.
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {shownVendors.map((vendor) => (
                        <VendorCard
                          key={vendor.id}
                          vendor={vendor}
                          expanded={expanded === vendor.id}
                          onToggle={() =>
                            setExpanded(expanded === vendor.id ? null : vendor.id)
                          }
                          onOpenEvidence={openEvidence}
                        />
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {tab === "Emails" && communications && (
            <Communications data={communications} live={live} />
          )}

          {tab === "Recommendation" && (
            <RecommendationPanel
              recommendation={recommendation}
              live={live}
              currencyFormat={(value) => formatMoney(value, recommendation?.currency ?? "IDR")}
            />
          )}
        </main>

        <aside className="min-w-0 lg:sticky lg:top-28 lg:self-start space-y-3">
          <div className="card overflow-hidden border border-slate-200 bg-white shadow-subtle rounded-xl">
            <button
              onClick={() => setLogOpen(!logOpen)}
              aria-expanded={logOpen}
              className="flex w-full items-center justify-between gap-3 p-4 text-left lg:cursor-default border-b border-slate-100"
            >
              <div className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-blue-600" />
                <span className="text-xs font-bold uppercase tracking-wider text-slate-800">
                  Agent Telemetry
                </span>
              </div>
              <div className="flex items-center gap-2">
                {live && (
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700 border border-emerald-200">
                    Active
                  </span>
                )}
                <span className="text-xs text-slate-500 lg:hidden">
                  {logOpen ? "Collapse ▲" : "Expand ▼"}
                </span>
              </div>
            </button>

            <div
              className={`scroll-thin max-h-[min(65vh,36rem)] overflow-y-auto p-4 ${
                logOpen ? "" : "hidden lg:block"
              }`}
            >
              <ActivityFeed entries={activity} vendorNames={vendorNames} />
            </div>
          </div>

          <p className="px-1 text-xs leading-relaxed text-slate-400">
Every entry is a stored workflow event, not a progress animation. The mission carries on if you close this tab.
          </p>
        </aside>
      </div>

      <EvidenceDrawer
        open={drawer !== null}
        title={drawer?.title ?? ""}
        records={drawer?.records ?? []}
        onClose={() => setDrawer(null)}
      />
    </div>
  );
}

function ReadoutCard({
  label,
  value,
  icon,
  hint,
  accent,
  alarm,
}: {
  label: string;
  value: string | number;
  icon?: string;
  hint?: string;
  accent?: boolean;
  alarm?: boolean;
}) {
  return (
    <div
      title={hint}
      className={`rounded-xl p-3 border transition-all ${
        alarm
          ? "border-rose-200 bg-rose-50/50"
          : accent
          ? "border-emerald-200 bg-emerald-50/50"
          : "border-slate-200 bg-white shadow-subtle"
      }`}
    >
      <dt className="flex items-center justify-between text-slate-500 text-xs font-medium">
        <span>{label}</span>
        {icon && <span className="opacity-60">{icon}</span>}
      </dt>
      <dd
        className={`mt-1 font-mono text-base font-bold tabular-nums leading-none ${
          alarm ? "text-rose-700" : accent ? "text-emerald-700" : "text-slate-900"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

