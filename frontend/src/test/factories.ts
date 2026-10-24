import type { Answer, Citation, Claim } from "../api/client";

export function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    chunk_id: "c1",
    document_id: "d1",
    document_title: "Parental Leave Policy",
    quote: "16 weeks of fully paid leave",
    quote_start: 36,
    quote_end: 64,
    heading_path: ["Parental Leave Policy", "How much leave you get"],
    page_start: null,
    page_end: null,
    ...overrides,
  };
}

export function claim(text: string, citations: Citation[]): Claim {
  return { text, citations, verified: true, verification: { quote_match: 1, entailment: "supported" } };
}

export function answer(overrides: Partial<Answer> = {}): Answer {
  return {
    id: "a1",
    thread_id: "t1",
    question: "How many weeks of paid parental leave?",
    status: "answered",
    scope: "internal",
    notices: [],
    egress: [],
    claims: [claim("Primary caregivers receive 16 weeks of paid leave.", [citation()])],
    refusal: null,
    dropped_claims: 0,
    latency_ms_by_stage: {},
    tokens_in: 0,
    tokens_out: 0,
    cost_usd: 0,
    created_at: "2026-10-20T10:00:00Z",
    ...overrides,
  };
}
