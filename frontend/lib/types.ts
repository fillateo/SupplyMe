//: Mirrors app/domain/models.py::Provenance — only the states
//: app/domain/evidence.py can actually compute.
export type Provenance =
  | "verified" | "direct_quote" | "publicly_listed"
  | "inferred" | "conflicting" | "unknown";

export type Fact = {
  value: string | number | null;
  provenance: Provenance;
  evidence_ids: string[];
  confidence: number;
};

export type Evidence = {
  id: string; claim: string; field: string | null; value: unknown;
  source_url: string | null; source_type: string; source_title: string | null;
  evidence_excerpt: string; retrieved_at: string; confidence: number;
  evidence_strength: "strong" | "moderate" | "weak" | "none";
};

export type Dimension = { name: string; score: number; explanation: string };
export type Trust = { dimensions: Dimension[]; overall: number };

export type BrandRelationship = {
  id: string; brand: string; classification: string; relationship_type: string;
  confidence: number; independent_sources: number; evidence_ids: string[]; notes: string;
};

export type Conflict = {
  id: string; field: string; status: string; resolution_action: string | null;
  preferred_value: unknown; preferred_reason: string; resolved_value: unknown;
  values: { value: unknown; source_type: string; source_url: string | null; excerpt: string }[];
};

//: Same rule again. The API also returns address, lat, lng and capabilities;
//: the console renders none of them, and coordinates have their own endpoint
//: (`/api/missions/{id}/map`) with no control behind it.
export type Vendor = {
  id: string; name: string; city: string | null; country: string | null;
  website: string | null; email: string | null; phone: string | null;
  status: string; node_keys: string[];
  moq: Fact; unit_price: Fact; lead_time_days: Fact;
  sample_lead_time_days: Fact; customization: Fact; payment_terms: Fact;
  currency: string | null; missing_fields: string[]; rejection_reasons: string[];
  evidence_ids: string[]; trust: Trust; evidence_count: number;
  brand_relationships: BrandRelationship[]; conflicts: Conflict[];
};

//: Only the fields the console renders. The API returns more (description,
//: depends_on, search_terms, status); adding one here means using it.
export type SupplyChainNode = {
  id: string; key: string; name: string; required: boolean;
  consolidates_with: string[]; rationale: string;
};

export type SearchScope = "city" | "country" | "global";

//: Only the fields the console renders — the same rule as SupplyChainNode
//: above. The API returns more (priorities, success_criteria, weights, and the
//: per-mission spend counters, which are also served as their own `spend`
//: block); declaring one here without using it makes this file a description of
//: the API rather than of the console, and the two then drift.
export type Mission = {
  id: string; objective: string; status: string; product: string | null;
  quantity: number | null; unit_spec: string | null; market: string | null;
  location: string | null; search_scope: SearchScope;
  emails_sent: number; created_at: string;
  //: Rendered on a stopped mission. The backend records why it stopped — a
  //: spend cap, a plan it could not act on — and a status chip alone says only
  //: "Stopped".
  failure_reason: string | null;
};


export type MissionCounts = {
  vendors: number; qualified: number; rejected: number; in_progress: number;
  evidence: number; open_conflicts: number;
  //: `emails_sent` is outreach budget consumed, including an attempt whose send
  //: failed. `emails_delivered` is what actually left the system. Show the
  //: second one to a human; the first is a cost figure.
  //: Optional because the console and the API are two Cloud Run services and
  //: either can be a revision ahead of the other.
  emails_sent: number; emails_delivered?: number;
  emails_responded: number; emails_awaiting: number;
  pending_approvals: number;
};

export type ActivityEntry = {
  id: string; event_id: string; type: string; status: string;
  payload: Record<string, unknown>; caused_by: string | null;
  created_at: string; recorded_at: number; latency_ms: number | null;
  emitted: string[]; error: string | null;
};

export type ScoreComponent = {
  name: string; weight: number; raw: number; contribution: number; explanation: string;
};

export type Selection = {
  node_key: string; node_name: string; vendor: Vendor; score: {
    total: number; disqualified: boolean; rejection_reasons: string[];
    strengths: string[]; components: ScoreComponent[];
  };
  trust: Trust; quote: { unit_price: number | null; currency: string; bundled: boolean;
    covered: string[]; missing: string[]; notes: string[] } | null;
  why?: string[];
};

export type Recommendation = {
  id: string; selections: Selection[]; alternatives: Selection[]; rejected: Selection[];
  risks: string[]; unknowns: string[]; next_actions: string[]; narrative: string;
  //: null when nothing was priced, or when the priced quotes are in more than
  //: one currency — the API refuses to add across currencies without an FX rate.
  estimated_unit_cost: number | null;
  //: The currency the suppliers quoted in, not the one the market implies.
  currency: string;
  //: How many of the selections `estimated_unit_cost` covers. A total over two
  //: priced components out of seven is not the unit cost of the product.
  //: Optional because the console and the API are two Cloud Run services and
  //: either can be a revision ahead of the other.
  priced_selections?: number;
  open_conflicts: string[];
};

export type Thread = {
  id: string; vendor_id: string; vendor_name: string; to_address: string;
  subject: string; status: string; follow_up_count: number;
  asked: string[]; answered: string[]; unanswered: string[]; commitments: string[];
  messages: { id: string; direction: string; subject: string; body: string; sent_at: string }[];
};

export type Approval = {
  id: string; vendor_id: string | null; action_type: string; summary: string;
  status: string; preview: Record<string, any>; created_at: string;
};
