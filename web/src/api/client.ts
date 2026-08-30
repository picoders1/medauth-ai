import type {
  ApiError,
  AuditTrail,
  Case,
  CaseStatus,
  Evidence,
  Recommendation,
  ReviewCase,
  ReviewResponse,
  SubmitCasePayload,
} from '../lib/types'

export interface Credentials {
  apiKey: string
  bearerToken?: string
}

/**
 * API client for MEDAUTH /api/v1.
 *
 * Two identities, deliberately:
 *  - `x-api-key` = the integrating system (caller) — which cases may be seen.
 *  - `Authorization: Bearer` = the authenticated human reviewer — who decided.
 * An API key can never stand in for a person (OD-43). Review actions therefore
 * send BOTH headers.
 */
export class Client {
  private apiKey: string
  private bearerToken?: string

  constructor(creds: Credentials) {
    this.apiKey = creds.apiKey
    this.bearerToken = creds.bearerToken
  }

  setCredentials(creds: Credentials) {
    this.apiKey = creds.apiKey
    this.bearerToken = creds.bearerToken
  }

  private headers(reviewer: boolean): HeadersInit {
    const h: Record<string, string> = { 'Content-Type': 'application/json' }
    if (this.apiKey) h['x-api-key'] = this.apiKey
    if (reviewer && this.bearerToken) h['Authorization'] = `Bearer ${this.bearerToken}`
    return h
  }

  private async send<T>(path: string, opts: { method?: string; body?: unknown; reviewer?: boolean } = {}): Promise<T> {
    const { method = 'GET', body, reviewer = false } = opts
    const res = await fetch(`/api/v1${path}`, {
      method,
      headers: this.headers(reviewer),
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (!res.ok) {
      let apiError: ApiError = { status: res.status }
      try {
        apiError = (await res.json()) as ApiError
        apiError.status = res.status
      } catch {
        /* non-JSON error body */
      }
      throw new ApiHttpError(apiError)
    }
    return (await res.json()) as T
  }

  // -- submit (caller) -------------------------------------------------------
  submitCase(payload: SubmitCasePayload) {
    return this.send<Case>(`/cases`, { method: 'POST', body: payload })
  }

  // -- caller-only reads ------------------------------------------------------
  getCase(caseId: string) {
    return this.send<Case>(`/cases/${encodeURIComponent(caseId)}`)
  }
  getStatus(caseId: string) {
    return this.send<CaseStatus>(`/cases/${encodeURIComponent(caseId)}/status`)
  }
  getRecommendation(caseId: string) {
    return this.send<Recommendation>(`/cases/${encodeURIComponent(caseId)}/recommendation`)
  }
  getEvidence(caseId: string) {
    return this.send<Evidence>(`/cases/${encodeURIComponent(caseId)}/evidence`)
  }
  getAudit(caseId: string) {
    return this.send<AuditTrail>(`/cases/${encodeURIComponent(caseId)}/audit`)
  }

  // -- reviewer-endpoints (need bearer) ------------------------------------
  getReviewView(caseId: string) {
    return this.send<ReviewCase>(`/cases/${encodeURIComponent(caseId)}/review`, { reviewer: true })
  }
  accept(caseId: string, comment: string | undefined, statedQualification: string) {
    return this.send<ReviewResponse>(`/cases/${encodeURIComponent(caseId)}/review/accept`, {
      method: 'POST',
      reviewer: true,
      body: { comment, stated_qualification: statedQualification },
    })
  }
  override(caseId: string, overrideOutcome: string, rationale: string, statedQualification: string) {
    return this.send<ReviewResponse>(`/cases/${encodeURIComponent(caseId)}/review/override`, {
      method: 'POST',
      reviewer: true,
      body: {
        override_outcome: overrideOutcome,
        rationale,
        stated_qualification: statedQualification,
      },
    })
  }
  requestInfo(caseId: string, requestedInformation: string, statedQualification: string) {
    return this.send<ReviewResponse>(`/cases/${encodeURIComponent(caseId)}/review/request-info`, {
      method: 'POST',
      reviewer: true,
      body: { requested_information: requestedInformation, stated_qualification: statedQualification },
    })
  }
}

export class ApiHttpError extends Error {
  body: ApiError
  constructor(body: ApiError) {
    super(typeof body.detail === 'string' ? body.detail : `Request failed (HTTP ${body.status})`)
    this.name = 'ApiHttpError'
    this.body = body
  }
}