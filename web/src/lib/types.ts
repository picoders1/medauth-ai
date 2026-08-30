export type CaseState =
  | 'CREATED'
  | 'SUBMITTED'
  | 'RECOMMENDATION_READY'
  | 'HUMAN_REVIEW'
  | 'FINAL_INFO'
  | 'CLOSED'

export interface Case {
  case_id: string
  case_version: number
  state: CaseState
  procedure_code: string
  code_system: string
  jurisdiction: string
  date_of_service: string
  input_sha256: string
  created_at: string
  updated_at: string
  request_id: string
}

export interface CaseStatus {
  case_id: string
  state: CaseState
  allowed_next: CaseState[]
  awaiting_human_review: boolean
  updated_at: string
  request_id: string
}

export interface Recommendation {
  case_id: string
  outcome: string
  decision_rule: string
  abstention_reason?: string | null
  resolution_state?: string | null
  resolution_reason?: string | null
  policy_type?: string | null
  policy_id?: string | null
  policy_version?: string | null
  provider_failure_kind?: string | null
  provider_failure_attribution?: string | null
  confidence_state: string
  human_review_required: boolean
  model_calls: number
  run_seq: number
  created_at: string
  request_id: string
}

export interface EvidenceItem {
  chunk_id: string
  policy_type?: string | null
  policy_id?: string | null
  policy_version?: string | null
  section?: string | null
  criterion_ids: string[]
}

export interface Evidence {
  case_id: string
  items: EvidenceItem[]
  empty_because_not_assessed: boolean
  request_id: string
}

export interface AuditEvent {
  event: string
  stage: string
  outcome?: string | null
  abstention_reason?: string | null
  resolution_state?: string | null
  provider_failure_kind?: string | null
  actor_type?: string | null
  correlation_id?: string | null
  created_at: string
}

export interface AuditTrail {
  case_id: string
  events: AuditEvent[]
  request_id: string
}

export interface ReviewHistory {
  action: string
  outcome?: string | null
  reviewer_principal_id: string
  identity_model: string
  authentication_method: string
  rationale?: string | null
  recommended_outcome_at_review?: string | null
  created_at: string
}

export interface EvidenceRef {
  chunk_id: string
  criterion_ids: string[]
  stage: string
}

export interface ReviewCase {
  case_id: string
  state: CaseState
  procedure_code: string
  code_system: string
  jurisdiction: string
  date_of_service: string
  input_sha256: string
  ai_recommendation?: string | null
  decision_rule?: string | null
  abstention_reason?: string | null
  routing_explanation?: string | null
  policy_type?: string | null
  policy_id?: string | null
  policy_version?: string | null
  resolution_state?: string | null
  resolution_reason?: string | null
  contradiction_state?: string | null
  provider_failure_kind?: string | null
  confidence_state?: string | null
  recommended_at?: string | null
  human_disposition?: string | null
  disposition_by?: string | null
  disposition_at?: string | null
  reviewer_principal_id: string
  reviewer_qualification?: string | null
  qualification_state?: string | null
  qualification_notice?: string | null
  evidence: EvidenceRef[]
  history: ReviewHistory[]
  available_actions: string[]
  audit_event_count: number
  request_id: string
}

export interface ReviewResponse {
  case_id: string
  action: string
  outcome?: string | null
  reviewer_id: string
  principal_type: string
  authentication_method: string
  identity_model: string
  recommended_outcome_at_review?: string | null
  case_state: CaseState
  created_at: string
  request_id: string
}

export interface SubmitCasePayload {
  case_id?: string
  clinical_note: string
  procedure_code: string
  code_system: string
  date_of_service: string
  diagnosis_codes?: string[]
  jurisdiction?: string
}

export interface ApiError {
  status: number
  code?: string
  detail?: string | string[]
  title?: string
  request_id?: string
}