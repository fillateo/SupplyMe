export type Provenance =
  | "verified" | "direct_quote" | "supplier_reported" | "publicly_listed"
  | "estimated" | "inferred" | "conflicting" | "unknown";

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

export type Vendor = {
  id: string; name: string; city: string | null; country: string | null;
  website: string | null; email: string | null; phone: string | null;
  address: string | null; lat: number | null; lng: number | null;
  status: string; node_keys: string[]; capabilities: string[];
  moq: Fact; unit_price: Fact; lead_time_days: Fact;
  sample_lead_time_days: Fact; customization: Fact; payment_terms: Fact;
  currency: string | null; missing_fields: string[]; rejection_reasons: string[];
  evidence_ids: string[]; trust: Trust; evidence_count: number;
  brand_relationships: BrandRelationship[]; conflicts: Conflict[];
};

export type SupplyChainNode = {
  id: string; key: string; name: string; description: string; required: boolean;
  status: string; depends_on: string[]; consolidates_with: string[];
  search_terms: string[]; rationale: string;
};

export type Mission = {
  id: string; objective: string; status: string; product: string | null;
  quantity: number | null; unit_spec: string | null; market: string | null;
  priorities: string[]; success_criteria: string[]; mode: string;
  emails_sent: number; calls_made: number; created_at: string;
  weights: Record<string, number>; failure_reason: string | null;
};

export type MissionCounts = {
  vendors: number; qualified: number; rejected: number; in_progress: number;
  evidence: number; open_conflicts: number; emails_sent: number;
  emails_responded: number; emails_awaiting: number; calls_completed: number;
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
  estimated_unit_cost: number | null; currency: string; open_conflicts: string[];
};

export type Thread = {
  id: string; vendor_id: string; vendor_name: string; to_address: string;
  subject: string; status: string; follow_up_count: number;
  asked: string[]; answered: string[]; unanswered: string[]; commitments: string[];
  messages: { id: string; direction: string; subject: string; body: string; sent_at: string }[];
};

export type Call = {
  id: string; vendor_id: string; vendor_name: string; to_number: string;
  status: string; reason: string; questions: string[];
  transcript: { speaker: string; text: string }[];
  answered_questions: Record<string, string>; unanswered_questions: string[];
  duration_seconds: number | null;
};

export type Approval = {
  id: string; vendor_id: string | null; action_type: string; summary: string;
  status: string; preview: Record<string, any>; created_at: string;
};
