/**
 * The case lifecycle. **Mirrors `app/case/lifecycle.py:CaseState` exactly** — this is a
 * copy of a server-owned vocabulary, not a UI model, and it may not gain a member the
 * server cannot emit or lose one the server can.
 *
 * `tests/unit/test_spa_contract_conformance.py` reads both this file and the Python enum
 * and fails on any divergence, because a silently wrong state name renders as a neutral
 * grey chip rather than as an error — a `FAILED` case that looks unremarkable is the
 * failure mode worth a test.
 */
export type CaseState =
  | 'RECEIVED'
  | 'PROCESSING'
  | 'RECOMMENDATION_READY'
  | 'NEEDS_INFO'
  | 'HUMAN_REVIEW'
  | 'FINALIZED'
  | 'FAILED'

/**
 * Tokens the server publishes in `available_actions`. Mirrors the literals built in
 * `app/case/review_view.py`. These answer "what does the case's STATE permit" and are
 * **not** an authorization answer — see `may_override` on {@link ReviewCase}.
 */
export type AvailableAction =
  | 'ACCEPT_RECOMMENDATION'
  | 'OVERRIDE_RECOMMENDATION'
  | 'REQUEST_INFORMATION'

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
  /** What the case STATE permits. Empty unless the case is in `HUMAN_REVIEW`. */
  available_actions: AvailableAction[]
  /**
   * What THIS reviewer may do, from the permissions their token was granted
   * (`app/identity/principal.py`). Separate from `available_actions` because state and
   * authority are separate gates server-side; the client must not collapse them.
   *
   * Informational only. `HumanReviewService.record` re-checks every permission.
   */
  may_review: boolean
  may_override: boolean
  may_finalize: boolean
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
  /**
   * **Required.** `SubmitCaseRequest.case_id` has no default server-side, and
   * `docs/architecture/application-lifecycle.md` §4 makes the id the caller's: a
   * duplicate submission is refused rather than deduplicated, so the server must not
   * mint one. Declaring it optional here produced a 422 on the documented flow.
   */
  case_id: string
  clinical_note: string
  procedure_code: string
  code_system: string
  date_of_service: string
  diagnosis_codes?: string[]
  /** Absent means jurisdictional policies do NOT apply - never that they do. */
  jurisdiction?: string
}

/**
 * The API's actual error envelope, verified against the running service:
 *   `{"error": "case_not_found", "detail": "...", "request_id": "...", "case_id": null}`
 *
 * The category key is `error`. There is no `code` and no `title` — the previous
 * declaration invented both, so the machine-readable category was never available to
 * the UI and `request_id` was never shown, which is the field a reviewer would need to
 * quote when asking why an action failed.
 */
export interface ApiError {
  /** HTTP status. Added by the client; not part of the server body. */
  status: number
  /** Machine-readable category, e.g. `not_authenticated`, `not_authorised`. */
  error?: string
  /** Human-readable message, or pydantic's validation-error list on a 422. */
  detail?: string | ValidationIssue[]
  request_id?: string
  case_id?: string | null
}

/** One entry of a FastAPI/pydantic 422 body. */
export interface ValidationIssue {
  type: string
  loc: (string | number)[]
  msg: string
}