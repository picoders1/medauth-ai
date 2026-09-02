/**
 * Regression tests for the API error envelope (defect 8).
 *
 * The console's `ApiError` declared `code` and `title`; the server sends `error`,
 * `detail`, `request_id` and `case_id`. The category was therefore never available and
 * `request_id` — the one thing a reviewer would quote when asking why an action failed —
 * was never shown. A 422's `detail` is a list, which the old client stringified into the
 * unhelpful "Request failed (HTTP 422)".
 *
 * The envelope shapes below are copied from live responses, and
 * `tests/api/test_spa_review_contract.py` asserts the server still produces them.
 */
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { ApiHttpError, describe as describeError } from './client.ts'
import type { ApiError } from '../lib/types.ts'

/** Verbatim from `GET /api/v1/cases/NOPE` with no credentials. */
const NOT_AUTHENTICATED: ApiError = {
  status: 401,
  error: 'not_authenticated',
  detail: 'missing x-api-key',
  request_id: '7e803dc37e074a4bbc94b05f8f3e5a9a',
  case_id: null,
}

/** Verbatim shape from `POST /api/v1/cases` with an empty body. */
const VALIDATION_FAILED: ApiError = {
  status: 422,
  detail: [
    { type: 'missing', loc: ['body', 'case_id'], msg: 'Field required' },
    { type: 'missing', loc: ['body', 'clinical_note'], msg: 'Field required' },
  ],
  request_id: '4da590a3d1b647ae8259be3ae613439d',
}

describe('the error envelope', () => {
  it('reads the message from detail', () => {
    assert.equal(new ApiHttpError(NOT_AUTHENTICATED).message, 'missing x-api-key')
  })

  it('exposes the category from `error`, not from `code`', () => {
    const err = new ApiHttpError(NOT_AUTHENTICATED)
    assert.equal(err.code, 'not_authenticated')
    // `code` and `title` were invented by the old client and are never sent.
    assert.equal((NOT_AUTHENTICATED as unknown as Record<string, unknown>).code, undefined)
    assert.equal((NOT_AUTHENTICATED as unknown as Record<string, unknown>).title, undefined)
  })

  it('keeps the request id so a reviewer can quote it', () => {
    assert.equal(new ApiHttpError(NOT_AUTHENTICATED).requestId, NOT_AUTHENTICATED.request_id)
  })

  it('keeps the whole envelope for anything else that needs it', () => {
    assert.deepEqual(new ApiHttpError(NOT_AUTHENTICATED).body, NOT_AUTHENTICATED)
  })

  it('is an Error, so existing `(x as Error).message` call sites keep working', () => {
    const err = new ApiHttpError(NOT_AUTHENTICATED)
    assert.ok(err instanceof Error)
    assert.equal(err.name, 'ApiHttpError')
  })
})

describe('a 422 body', () => {
  it('names the fields instead of reporting a bare status', () => {
    // The defect: this used to read "Request failed (HTTP 422)", which tells the
    // submitter nothing about which field the server refused.
    const message = new ApiHttpError(VALIDATION_FAILED).message
    assert.match(message, /case_id: Field required/)
    assert.match(message, /clinical_note: Field required/)
    assert.doesNotMatch(message, /HTTP 422/)
  })

  it('strips the "body" prefix pydantic puts on every loc', () => {
    assert.doesNotMatch(new ApiHttpError(VALIDATION_FAILED).message, /body\./)
  })
})

describe('degraded envelopes', () => {
  it('falls back to the category when there is no detail', () => {
    assert.equal(
      describeError({ status: 503, error: 'provider_unavailable' }),
      'provider_unavailable (HTTP 503)',
    )
  })

  it('falls back to the status when the body is not the envelope at all', () => {
    // A proxy error or a truncated response still has to render something.
    assert.equal(describeError({ status: 502 }), 'Request failed (HTTP 502)')
  })

  it('does not mistake an empty detail for a message', () => {
    assert.equal(describeError({ status: 500, detail: '' }), 'Request failed (HTTP 500)')
    assert.equal(describeError({ status: 500, detail: [] }), 'Request failed (HTTP 500)')
  })

  it('survives an issue with no loc', () => {
    const message = describeError({
      status: 422,
      detail: [{ type: 'value_error', loc: [], msg: 'malformed' }],
    })
    assert.equal(message, 'malformed')
  })
})
