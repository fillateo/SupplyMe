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

const TABS = ["Supply chain", "Suppliers", "Communications", "Recommendation"] as const;
type Tab = (typeof TABS)[number];

const TERMINAL = new Set(["completed", "failed"]);

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
  const [tab, setTab] = useState<Tab>("Supply chain");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<{ title: string; records: Evidence[] } | null>(null);

  const refresh = useCallback(async () => {
    if (!id) return;
    setLoadError(null);
    const [overview, vendorList, activityLog, evidenceList, approvalList, comms] =
      await Promise.all([
        api.mission(id), api.vendors(id), api.activity(id),
        api.evidence(id), api.approvals(id), api.communications(id),
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
  }, [id]);

  useEffect(() => {
    refresh().catch((error) => setLoadError({ status: error?.status }));
  }, [refresh]);

  // While a mission is live the workflow is running somewhere else entirely, so
  // the console polls rather than assuming its own state is current.
  useEffect(() => {
    if (!mission || TERMINAL.has(mission.status)) return;
    const timer = setInterval(
      () => refresh().catch((error) => setLoadError({ status: error?.status })),
      2000,
    );
    return () => clearInterval(timer);
  }, [mission, refresh]);

  const vendorNames = useMemo(
    () => Object.fromEntries(vendors.map((vendor) => [vendor.id, vendor.name])),
    [vendors],
  );
  const evidenceById = useMemo(
    () => Object.fromEntries(evidence.map((record) => [record.id, record])),
    [evidence],
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
    await api.decide(approvalId, approved);
    await refresh();
  }

  if (!mission || !counts) {
    if (loadError) {
      // A failure that reads as "loading" is the console lying about what it
      // knows. Say which failure it was, because the two have different fixes.
      const gone = loadError.status === 404;
      return (
        <main className="mx-auto max-w-2xl px-8 py-16">
          <h1 className="font-serif text-2xl text-ink">
            {gone ? "This mission is no longer here." : "Cannot reach the API."}
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            {gone
              ? "Missions are held in memory, so restarting the API clears them. The " +
                "record is gone rather than hidden — set VDS_USE_CLOUD_INFRA=true with " +
                "a Firestore database to keep missions across restarts."
              : "The console reached the browser but not the API. Check that it is " +
                "running on :8080, then reload."}
          </p>
          <Link
            href="/"
            className="mt-6 inline-block rounded-md border border-rule px-4 py-2 font-mono
                       text-2xs uppercase tracking-[0.08em] text-muted hover:border-petrol"
          >
            All missions
          </Link>
        </main>
      );
    }
    return <main className="px-8 py-16 text-sm text-muted">Loading mission…</main>;
  }

  const live = !TERMINAL.has(mission.status);

  return (
    <div className="min-h-screen">
      <header className="border-b border-rule bg-surface">
        <div className="mx-auto max-w-[1400px] px-8 py-5">
          <div className="flex items-start justify-between gap-8">
            <div className="min-w-0">
              <Link href="/" className="col-label hover:text-petrol">
                ← All missions
              </Link>
              <h1 className="mt-2 max-w-3xl font-serif text-xl leading-snug text-ink">
                {mission.objective}
              </h1>
              <p className="mt-2 font-mono text-2xs uppercase tracking-[0.08em] text-faint">
                {mission.product ?? "reading the objective"}
                {mission.quantity ? ` · ${mission.quantity.toLocaleString()} units` : ""}
                {mission.market ? ` · ${mission.market}` : ""} · {mission.mode} mode
              </p>
            </div>
            <StatusChip status={mission.status} live={live} />
          </div>

          <dl className="mt-5 flex flex-wrap gap-x-8 gap-y-2">
            <Metric label="Categories" value={nodes.length} />
            <Metric label="Suppliers" value={counts.vendors} />
            <Metric label="Qualified" value={counts.qualified} />
            <Metric label="Ruled out" value={counts.rejected} />
            <Metric label="Emails" value={`${counts.emails_responded}/${counts.emails_sent}`}
              hint="replied / sent" />
            <Metric label="Disagreements" value={counts.open_conflicts}
              tone={counts.open_conflicts > 0 ? "rose" : undefined} />
            <Metric label="Sources" value={counts.evidence} />
          </dl>
        </div>
      </header>

      {pending.length > 0 && (
        <section className="border-b border-rose/30 bg-rose-light/50">
          <div className="mx-auto max-w-[1400px] space-y-3 px-8 py-4">
            {pending.map((approval) => (
              <div key={approval.id} className="flex items-start justify-between gap-6">
                <div className="min-w-0">
                  <p className="text-sm text-ink">{approval.summary}</p>
                  {approval.preview?.subject && (
                    <p className="mt-1 font-mono text-xs text-muted">
                      {approval.preview.subject}
                    </p>
                  )}
                  {approval.preview?.questions && (
                    <ul className="mt-1 space-y-0.5">
                      {(approval.preview.questions as string[]).map((question, index) => (
                        <li key={index} className="text-xs text-muted">
                          · {question}
                        </li>
                      ))}
                    </ul>
                  )}
                  {approval.preview?.body && (
                    <details className="mt-1.5">
                      <summary className="col-label cursor-pointer hover:text-petrol">
                        Read it first
                      </summary>
                      <pre className="mt-2 whitespace-pre-wrap rounded-sm bg-surface px-3 py-2 font-mono text-xs text-ink">
                        {approval.preview.body as string}
                      </pre>
                    </details>
                  )}
                </div>
                <div className="flex shrink-0 gap-2">
                  <button
                    onClick={() => decide(approval.id, true)}
                    className="rounded-md bg-petrol px-4 py-2 font-mono text-2xs uppercase
                               tracking-[0.1em] text-white hover:bg-petrol-deep"
                  >
                    Send it
                  </button>
                  <button
                    onClick={() => decide(approval.id, false)}
                    className="rounded-md border border-rule px-4 py-2 font-mono text-2xs
                               uppercase tracking-[0.1em] text-muted hover:bg-surface"
                  >
                    Don&apos;t
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="mx-auto grid max-w-[1400px] gap-8 px-8 py-8 lg:grid-cols-[1fr_340px]">
        <main className="min-w-0">
          <nav className="mb-6 flex gap-1 border-b border-rule">
            {TABS.map((name) => (
              <button
                key={name}
                onClick={() => setTab(name)}
                className={`-mb-px border-b-2 px-4 py-2.5 font-mono text-2xs uppercase
                            tracking-[0.1em] transition-colors ${
                              tab === name
                                ? "border-petrol text-ink"
                                : "border-transparent text-faint hover:text-muted"
                            }`}
              >
                {name}
              </button>
            ))}
          </nav>

          {tab === "Supply chain" && <SupplyChain nodes={nodes} vendors={vendors} />}

          {tab === "Suppliers" && (
            <div className="space-y-3">
              {vendors.length === 0 && (
                <p className="py-8 text-sm text-muted">
                  No suppliers found yet. Discovery runs one branch per category.
                </p>
              )}
              {vendors.map((vendor) => (
                <VendorCard
                  key={vendor.id}
                  vendor={vendor}
                  expanded={expanded === vendor.id}
                  onToggle={() => setExpanded(expanded === vendor.id ? null : vendor.id)}
                  onOpenEvidence={openEvidence}
                />
              ))}
            </div>
          )}

          {tab === "Communications" && communications && (
            <Communications data={communications} />
          )}

          {tab === "Recommendation" && (
            <RecommendationPanel
              recommendation={recommendation}
              live={live}
              currencyFormat={(value) =>
                formatMoney(value, recommendation?.currency ?? "IDR")
              }
            />
          )}
        </main>

        <aside className="lg:sticky lg:top-8 lg:self-start">
          <div className="card p-5">
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="col-label">What it did</h2>
              {live && (
                <span className="flex items-center gap-1.5 font-mono text-2xs text-petrol">
                  <span className="h-1.5 w-1.5 animate-breathe rounded-full bg-petrol" />
                  running
                </span>
              )}
            </div>
            <div className="max-h-[calc(100vh-14rem)] overflow-y-auto">
              <ActivityFeed entries={activity} vendorNames={vendorNames} />
            </div>
          </div>
          <p className="mt-3 px-1 text-2xs leading-relaxed text-faint">
            Every line is a stored workflow event. Close this tab and the mission keeps
            going; reopen it and this is where it got to.
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

function Metric({
  label, value, hint, tone,
}: {
  label: string; value: string | number; hint?: string; tone?: string;
}) {
  return (
    <div>
      <dt className="col-label">{label}</dt>
      <dd
        className={`figure mt-0.5 text-lg ${tone === "rose" ? "text-rose" : "text-ink"}`}
        title={hint}
      >
        {value}
      </dd>
    </div>
  );
}
