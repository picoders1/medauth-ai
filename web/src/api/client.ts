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
        apiError = { ...((await res.json()) as ApiError), status: res.status }
      } catch {
        /* non-JSON error body */
      }
      // The request id also rides on a response header, and is present even when the
      // body is not JSON at all (a proxy error, a truncated response). Prefer the body,
      // fall back to the header, so the id a reviewer would quote is not lost in the
      // cases where it is most needed.
      apiError.request_id ??= res.headers.get('x-medauth-request-id') ?? undefined
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

/**
 * An error the API returned, carrying its whole envelope.
 *
 * The envelope is `{error, detail, request_id, case_id}` - verified against the running
 * service. `detail` is a string on most errors and pydantic's issue list on a 422, and
 * the previous client stringified neither, so a validation failure surfaced as the
 * unhelpful "Request failed (HTTP 422)".
 */
export class ApiHttpError extends Error {
  body: ApiError
  /** Machine-readable category, e.g. `not_authenticated`. */
  readonly code: string | undefined
  /** For the reviewer to quote - every audit event and log line carries the same id. */
  readonly requestId: string | undefined

  constructor(body: ApiError) {
    super(describe(body))
    this.name = 'ApiHttpError'
    this.body = body
    this.code = body.error
    this.requestId = body.request_id
  }
}

/** The most specific message the envelope supports, never a bare status. */
export function describe(body: ApiError): string {
  const { detail } = body
  if (typeof detail === 'string' && detail.length > 0) return detail
  if (Array.isArray(detail) && detail.length > 0) {
    // "clinical_note: Field required" reads as an instruction; "HTTP 422" does not.
    return detail
      .map((issue) => {
        const field = issue.loc?.filter((part) => part !== 'body').join('.')
        return field ? `${field}: ${issue.msg}` : issue.msg
      })
      .join('; ')
  }
  if (body.error) return `${body.error} (HTTP ${body.status})`
  return `Request failed (HTTP ${body.status})`
}