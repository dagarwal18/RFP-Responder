export const STAGES = [
  { key: 'A1_INTAKE', label: 'A1 — Intake', status: 'INTAKE_COMPLETE' },
  { key: 'A2_STRUCTURING', label: 'A2 — Structuring', status: 'STRUCTURING' },
  { key: 'A3_GO_NO_GO', label: 'A3 — Go / No-Go', status: 'GO_NO_GO' },
  { key: 'B1_REQUIREMENTS_EXTRACTION', label: 'B1 — Requirement Extract', status: 'EXTRACTING_REQUIREMENTS' },
  { key: 'B2_REQUIREMENTS_VALIDATION', label: 'B2 — Requirement Valid.', status: 'VALIDATING_REQUIREMENTS' },
  { key: 'C1_ARCHITECTURE_PLANNING', label: 'C1 — Architecture Plan', status: 'ARCHITECTURE_PLANNING' },
  { key: 'C2_REQUIREMENT_WRITING', label: 'C2 — Response Writing', status: 'WRITING_RESPONSES' },
  { key: 'C3_NARRATIVE_ASSEMBLY', label: 'C3 — Narrative Assembly', status: 'ASSEMBLING_NARRATIVE' },
  { key: 'D1_TECHNICAL_VALIDATION', label: 'D1 — Technical Validation', status: 'TECHNICAL_VALIDATION' },
  { key: 'E1_COMMERCIAL', label: 'E1 — Commercial Review', status: 'COMMERCIAL_LEGAL_REVIEW' },
  { key: 'E2_LEGAL', label: 'E2 — Legal Review', status: 'COMMERCIAL_LEGAL_REVIEW' },
  { key: 'H1_HUMAN_VALIDATION', label: 'H1 — Human Validation', status: 'AWAITING_HUMAN_VALIDATION' },
  { key: 'F1_FINAL_READINESS', label: 'F1 — Finalize & Submit', status: 'SUBMITTED' },
] as const;

export type StageKey = typeof STAGES[number]['key'];

export type RunStatus =
  | 'INTAKE_COMPLETE'
  | 'STRUCTURING'
  | 'GO_NO_GO'
  | 'EXTRACTING_REQUIREMENTS'
  | 'VALIDATING_REQUIREMENTS'
  | 'ARCHITECTURE_PLANNING'
  | 'WRITING_RESPONSES'
  | 'ASSEMBLING_NARRATIVE'
  | 'TECHNICAL_VALIDATION'
  | 'COMMERCIAL_LEGAL_REVIEW'
  | 'AWAITING_HUMAN_VALIDATION'
  | 'SUBMITTED'
  | 'RUNNING'
  | 'FAILED';

export interface Run {
  run_id: string;
  filename?: string;
  status: RunStatus;
  created_at?: string;
  review_status?: string;
}

export interface KBStats {
  vectors: number;
  namespaces: number;
  configs: number;
}

export interface KBFile {
  filename: string;
  doc_type: string;
  chunks: number;
  uploaded_at?: string;
}

export interface Policy {
  id: string;
  text: string;
  category: string;
  severity: string;
  source_section?: string;
}

export interface CompanyProfile {
  name: string;
  description: string;
  headquarters: string;
  website: string;
}

export interface LogEntry {
  time: string;
  message: string;
  type: 'info' | 'success' | 'error' | 'default';
}
