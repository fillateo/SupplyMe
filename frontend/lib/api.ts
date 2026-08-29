import type {
  Approval, ActivityEntry, Call, Evidence, Mission, MissionCounts,
  Recommendation, SupplyChainNode, Thread, Vendor,
} from "./types";

/** Requests go to the Next.js origin and are proxied server-side (next.config.mjs). */
async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => get<{ mode: string; approval_policy: string; providers: Record<string, string>; notes: string[] }>("/api/health"),
  missions: () => get<Mission[]>("/api/missions"),
  createMission: (objective: string) => send<Mission>("/api/missions", "POST", { objective }),
  mission: (id: string) =>
    get<{ mission: Mission; supply_chain: SupplyChainNode[]; counts: MissionCounts }>(`/api/missions/${id}`),
  vendors: (id: string) => get<Vendor[]>(`/api/missions/${id}/vendors`),
  vendor: (id: string, vendorId: string) =>
    get<{ vendor: Vendor; trust: Vendor["trust"]; evidence: Evidence[];
      brand_relationships: Vendor["brand_relationships"]; conflicts: Vendor["conflicts"];
      quotes: any[]; threads: Thread[]; calls: Call[] }>(`/api/missions/${id}/vendors/${vendorId}`),
  evidence: (id: string) => get<Evidence[]>(`/api/missions/${id}/evidence`),
  activity: (id: string) => get<ActivityEntry[]>(`/api/missions/${id}/activity`),
  communications: (id: string) =>
    get<{ email: { sent: number; responded: number; awaiting: number; threads: Thread[] };
      calls: { completed: number; scheduled: number; failed: number; items: Call[] } }>(
      `/api/missions/${id}/communications`),
  recommendation: (id: string) => get<Recommendation>(`/api/missions/${id}/recommendation`),
  approvals: (id: string) => get<Approval[]>(`/api/missions/${id}/approvals`),
  decide: (approvalId: string, approved: boolean) =>
    send<Approval>(`/api/approvals/${approvalId}`, "POST", { approved }),
  setPriorities: (id: string, priorities: string[]) =>
    send<{ weights: Record<string, number> }>(`/api/missions/${id}/weights`, "PUT", { priorities }),
};

export const TERMINAL_STATUSES = new Set(["completed", "failed"]);
