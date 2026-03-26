const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const WS_BASE = API_BASE.replace(/^http/, 'ws');

export { API_BASE, WS_BASE };

export const CHECKPOINT_AGENT_ORDER = [
  'a1_intake',
  'a2_structuring',
  'a3_go_no_go',
  'b1_requirements_extraction',
  'b2_requirements_validation',
  'c1_architecture_planning',
  'c2_requirement_writing',
  'c3_narrative_assembly',
  'd1_technical_validation',
  'commercial_legal_parallel',
  'h1_human_validation_prepare',
  'f1_final_readiness',
] as const;

export const CHECKPOINT_LABELS: Record<string, string> = {
  a1_intake: 'A1 Intake',
  a2_structuring: 'A2 Structuring',
  a3_go_no_go: 'A3 Go / No-Go',
  b1_requirements_extraction: 'B1 Requirements Extract',
  b2_requirements_validation: 'B2 Requirements Validation',
  c1_architecture_planning: 'C1 Architecture Planning',
  c2_requirement_writing: 'C2 Requirement Writing',
  c3_narrative_assembly: 'C3 Narrative Assembly',
  d1_technical_validation: 'D1 Technical Validation',
  commercial_legal_parallel: 'E1 + E2 Commercial / Legal',
  h1_human_validation_prepare: 'H1 Human Validation',
  f1_final_readiness: 'F1 Final Readiness',
};

const RUN_STAGE_ALIASES: Record<string, string> = {
  A1_INTAKE: 'A1_INTAKE',
  a1_intake: 'A1_INTAKE',
  A2_STRUCTURING: 'A2_STRUCTURING',
  a2_structuring: 'A2_STRUCTURING',
  A3_GO_NO_GO: 'A3_GO_NO_GO',
  a3_go_no_go: 'A3_GO_NO_GO',
  B1_REQUIREMENTS_EXTRACTION: 'B1_REQUIREMENTS_EXTRACTION',
  b1_requirements_extraction: 'B1_REQUIREMENTS_EXTRACTION',
  B2_REQUIREMENTS_VALIDATION: 'B2_REQUIREMENTS_VALIDATION',
  b2_requirements_validation: 'B2_REQUIREMENTS_VALIDATION',
  C1_ARCHITECTURE_PLANNING: 'C1_ARCHITECTURE_PLANNING',
  c1_architecture_planning: 'C1_ARCHITECTURE_PLANNING',
  C2_REQUIREMENT_WRITING: 'C2_REQUIREMENT_WRITING',
  c2_requirement_writing: 'C2_REQUIREMENT_WRITING',
  C3_NARRATIVE_ASSEMBLY: 'C3_NARRATIVE_ASSEMBLY',
  c3_narrative_assembly: 'C3_NARRATIVE_ASSEMBLY',
  D1_TECHNICAL_VALIDATION: 'D1_TECHNICAL_VALIDATION',
  d1_technical_validation: 'D1_TECHNICAL_VALIDATION',
  E1_COMMERCIAL: 'E1_COMMERCIAL',
  e1_commercial: 'E1_COMMERCIAL',
  E2_LEGAL: 'E2_LEGAL',
  e2_legal: 'E2_LEGAL',
  COMMERCIAL_LEGAL_PARALLEL: 'E1_COMMERCIAL',
  commercial_legal_parallel: 'E1_COMMERCIAL',
  H1_HUMAN_VALIDATION: 'H1_HUMAN_VALIDATION',
  H1_HUMAN_VALIDATION_PREPARE: 'H1_HUMAN_VALIDATION',
  h1_human_validation_prepare: 'H1_HUMAN_VALIDATION',
  F1_FINAL_READINESS: 'F1_FINAL_READINESS',
  f1_final_readiness: 'F1_FINAL_READINESS',
};

export function normalizeStageKey(value: string | null | undefined): string {
  if (!value) return '';
  return RUN_STAGE_ALIASES[String(value).trim()] || String(value).trim();
}

/* ── Core fetch helper ─────────────────────────────────── */

export async function apiFetch<T = unknown>(path: string, opts: RequestInit = {}): Promise<T> {
  const isFormData = opts.body instanceof FormData;
  const headers = new Headers(opts.headers || {});
  if (!isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }

  return res.json();
}

/* ── Backend → Frontend normalization helpers ────────────
 *
 * The FastAPI backend uses `rfp_id` and returns flat arrays
 * while the Next.js frontend expects `run_id` and wrapped
 * objects like `{ runs: [...] }`.  These helpers bridge the
 * gap without modifying either side's core logic.
 * ──────────────────────────────────────────────────────── */

/* eslint-disable @typescript-eslint/no-explicit-any */

/** Map a single backend run object → frontend Run shape */
function normalizeRun(r: any) {
  return {
    run_id: r.rfp_id ?? r.run_id ?? '',
    filename: r.filename ?? '',
    status: r.status ?? 'UNKNOWN',
    created_at: r.started_at ?? r.created_at ?? '',
    review_status: r.review_status,
  };
}

/** /api/rfp/list → { runs: Run[] } */
export async function fetchRuns() {
  const raw = await apiFetch<any>('/api/rfp/list');
  const arr = Array.isArray(raw) ? raw : (raw.runs ?? raw ?? []);
  return { runs: arr.map(normalizeRun) };
}

/** /api/rfp/{rfp_id}/status */
export async function fetchRunStatus(rfpId: string) {
  return apiFetch<any>(`/api/rfp/${rfpId}/status`);
}

/** /api/rfp/upload → { run_id: string, ... } */
export async function uploadRfp(form: FormData) {
  const res = await fetch(`${API_BASE}/api/rfp/upload`, {
    method: 'POST',
    body: form,
    // Let the browser set Content-Type with multipart boundary natively
  });
  if (!res.ok) {
    throw new Error(`Upload failed: ${res.status} ${res.statusText}`);
  }
  const raw = await res.json();
  return {
    run_id: raw.rfp_id ?? raw.run_id ?? '',
    status: raw.status ?? '',
    message: raw.message ?? '',
  };
}

/** /api/rfp/{rfp_id}/checkpoints */
export async function fetchCheckpoints(rfpId: string) {
  return apiFetch<any>(`/api/rfp/${rfpId}/checkpoints`);
}

/** /api/rfp/{rfp_id}/rerun */
export async function rerunPipeline(rfpId: string, startFrom: string) {
  return apiFetch<any>(`/api/rfp/${rfpId}/rerun?start_from=${startFrom}`, { method: 'POST' });
}

/** /api/rfp/{rfp_id}/checkpoints DELETE */
export async function clearCheckpoints(rfpId: string) {
  return apiFetch<any>(`/api/rfp/${rfpId}/checkpoints`, { method: 'DELETE' });
}

/** Build the full URL for downloading the generated document */
export function getDownloadUrl(rfpId: string): string {
  return `${API_BASE}/api/rfp/${rfpId}/download`;
}

export async function fetchReviewPackage(rfpId: string) {
  return apiFetch<any>(`/api/rfp/${rfpId}/review`);
}

export async function saveReviewComments(rfpId: string, comments: unknown[]) {
  return apiFetch<any>(`/api/rfp/${rfpId}/review/comments`, {
    method: 'PUT',
    body: JSON.stringify({ comments }),
  });
}

export async function submitReviewDecision(rfpId: string, body: {
  decision: string;
  reviewer?: string;
  summary?: string;
  rerun_from?: string;
  comments?: unknown[];
}) {
  return apiFetch<any>(`/api/rfp/${rfpId}/review/decision`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** /api/knowledge/status → { vectors, namespaces, configs } */
export async function fetchKBStats() {
  const raw = await apiFetch<any>('/api/knowledge/status');
  const pc = raw.pinecone ?? {};
  const mg = raw.mongodb ?? {};

  // pc.namespaces is an object like { "RFP-XXX": 50, ... } — count its keys
  const nsValue = pc.namespaces;
  const nsCount = typeof nsValue === 'number' ? nsValue
    : (nsValue && typeof nsValue === 'object' ? Object.keys(nsValue).length : 0);

  // mg.configs is an array of config type strings — use its length
  const cfgValue = mg.configs;
  const cfgCount = typeof cfgValue === 'number' ? cfgValue
    : (Array.isArray(cfgValue) ? cfgValue.length : 0);

  return {
    vectors: pc.total_vectors ?? pc.total_vector_count ?? 0,
    namespaces: nsCount,
    configs: cfgCount,
  };
}

/** /api/knowledge/files → { files: KBFile[] } */
export async function fetchKBFiles() {
  const raw = await apiFetch<any>('/api/knowledge/files');
  const arr = Array.isArray(raw) ? raw : (raw.files ?? []);
  return {
    files: arr.map((f: any) => ({
      filename: f.filename ?? '',
      doc_type: f.doc_type ?? '',
      chunks: f.chunks_stored ?? f.chunks ?? 0,
      uploaded_at: f.uploaded_at ?? '',
    })),
  };
}

/** /api/knowledge/policies → { policies: Policy[] } */
export async function fetchPolicies() {
  const raw = await apiFetch<any>('/api/knowledge/policies');
  const arr = Array.isArray(raw) ? raw : (raw.policies ?? []);
  return {
    policies: arr.map((p: any) => ({
      id: p.id ?? p.policy_id ?? '',
      text: p.policy_text ?? p.text ?? '',
      category: p.category ?? '',
      severity: p.severity ?? '',
      source_section: p.source_section ?? '',
    })),
  };
}

export async function createPolicy(body: {
  text: string;
  category: string;
  severity: string;
  source_section?: string;
}) {
  return apiFetch<any>('/api/knowledge/policies', {
    method: 'POST',
    body: JSON.stringify({
      policy_text: body.text,
      category: body.category,
      severity: body.severity,
      source_section: body.source_section || '',
      rule_type: 'requirement',
    }),
  });
}

export async function updatePolicy(policyId: string, body: {
  text: string;
  category: string;
  severity: string;
  source_section?: string;
}) {
  return apiFetch<any>(`/api/knowledge/policies/${policyId}`, {
    method: 'PUT',
    body: JSON.stringify({
      policy_text: body.text,
      category: body.category,
      severity: body.severity,
      source_section: body.source_section || '',
      rule_type: 'requirement',
    }),
  });
}

export async function deletePolicy(policyId: string) {
  return apiFetch<any>(`/api/knowledge/policies/${policyId}`, { method: 'DELETE' });
}

export async function deleteAllPolicies() {
  return apiFetch<any>('/api/knowledge/policies', { method: 'DELETE' });
}

/** /api/knowledge/company-profile → CompanyProfile */
export async function fetchCompanyProfile() {
  const raw = await apiFetch<any>('/api/knowledge/company-profile');
  const p = raw.profile ?? raw ?? {};
  return {
    name: p.company_name ?? p.name ?? '',
    description: p.company_description ?? p.description ?? '',
    headquarters: p.headquarters ?? '',
    website: p.website ?? '',
  };
}

export async function saveCompanyProfile(profile: {
  name: string;
  description: string;
  headquarters: string;
  website: string;
}) {
  return apiFetch<any>('/api/knowledge/company-profile', {
    method: 'PUT',
    body: JSON.stringify({
      company_name: profile.name,
      company_description: profile.description,
      headquarters: profile.headquarters,
      website: profile.website,
    }),
  });
}

/* ── Utilities (unchanged) ───────────────────────────── */

export function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

export function escapeHtml(value: string = ''): string {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function truncateText(value: string = '', maxLength: number = 260): string {
  const text = String(value || '').trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength).trimEnd()}…`;
}

export function formatTime(date: Date = new Date()): string {
  return date.toLocaleTimeString();
}
