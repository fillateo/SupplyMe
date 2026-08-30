import type {
  Approval, ActivityEntry, Evidence, Mission, MissionCounts,
  Recommendation, SearchScope, SupplyChainNode, Thread, Vendor,
} from "./types";

/**
 * Carries the status code, so a caller can tell "this mission is gone" from
 * "the API is down". Without it every failure is one opaque string and the
 * console can only say "loading" forever.
 */
export class ApiError extends Error {
  constructor(readonly status: number, readonly path: string) {
    super(`${path} returned ${status}`);
    this.name = "ApiError";
  }
}

/** Requests go to the Next.js origin and are proxied server-side (next.config.mjs). */
async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(response.status, path);
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
  health: () => get<{ approval_policy: string; providers: Record<string, string>; notes: string[] }>("/api/health"),
  missions: () => get<Mission[]>("/api/missions"),
  createMission: (objective: string, where?: { location?: string; scope?: SearchScope }) =>
    send<Mission>("/api/missions", "POST", {
      objective,
      location: where?.location?.trim() || null,
      scope: where?.scope ?? "country",
    }),
  mission: (id: string) =>
    get<{ mission: Mission; supply_chain: SupplyChainNode[]; counts: MissionCounts }>(`/api/missions/${id}`),
  vendors: (id: string) => get<Vendor[]>(`/api/missions/${id}/vendors`),
  vendor: (id: string, vendorId: string) =>
    get<{ vendor: Vendor; trust: Vendor["trust"]; evidence: Evidence[];
      brand_relationships: Vendor["brand_relationships"]; conflicts: Vendor["conflicts"];
      quotes: any[]; threads: Thread[] }>(`/api/missions/${id}/vendors/${vendorId}`),
  evidence: (id: string) => get<Evidence[]>(`/api/missions/${id}/evidence`),
  activity: (id: string) => get<ActivityEntry[]>(`/api/missions/${id}/activity`),
  communications: (id: string) =>
    get<{ email: { sent: number; responded: number; awaiting: number; threads: Thread[] } }>(
      `/api/missions/${id}/communications`),
  recommendation: (id: string) => get<Recommendation>(`/api/missions/${id}/recommendation`),
  approvals: (id: string) => get<Approval[]>(`/api/missions/${id}/approvals`),
  decide: (approvalId: string, approved: boolean) =>
    send<Approval>(`/api/approvals/${approvalId}`, "POST", { approved }),
  setPriorities: (id: string, priorities: string[]) =>
    send<{ weights: Record<string, number> }>(`/api/missions/${id}/weights`, "PUT", { priorities }),
};

export const TERMINAL_STATUSES = new Set(["completed", "failed"]);
