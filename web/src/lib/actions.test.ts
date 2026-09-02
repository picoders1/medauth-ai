/**
 * Regression tests for the review-action gating (defects 2, 3 and 4).
 *
 * Run with Node's built-in test runner and native type stripping — `npm test`. No test
 * framework is installed: R-31 names the npm supply-chain surface as a risk in this
 * project, and a reviewer console does not need to pay it for a truth table.
 *
 * The **vocabulary** these fixtures use is not asserted here — a frontend test can only
 * check what the frontend author typed, which is how the original defect survived. That
 * the tokens and permission flags match the server is
 * `tests/unit/test_spa_contract_conformance.py` and `tests/api/test_spa_review_contract.py`.
 */
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { gateActions, requiresText } from './actions.ts'
import type { AvailableAction, CaseState, ReviewCase } from './types.ts'

type GateInput = Parameters<typeof gateActions>[0]

const ALL_ACTIONS: AvailableAction[] = [
  'ACCEPT_RECOMMENDATION',
  'OVERRIDE_RECOMMENDATION',
  'REQUEST_INFORMATION',
]

/** A reviewer in HUMAN_REVIEW holding everything, unless overridden. */
function view(overrides: Partial<GateInput> = {}): GateInput {
  return {
    state: 'HUMAN_REVIEW' as CaseState,
    available_actions: ALL_ACTIONS,
    may_review: true,
    may_override: true,
    may_finalize: true,
    ...overrides,
  }
}

describe('state gate', () => {
  it('enables every action for a fully-permissioned reviewer on an open case', () => {
    const gates = gateActions(view())
    for (const action of ALL_ACTIONS) {
      assert.equal(gates[action].enabled, true, `${action} was not enabled`)
      assert.equal(gates[action].blockedReason, null)
    }
  })

  it('disables every action when the case publishes none', () => {
    // Defect 4: accept and request-info consulted nothing and stayed clickable on a
    // finalised case, so the UI offered actions the service would refuse.
    for (const state of ['RECEIVED', 'PROCESSING', 'NEEDS_INFO', 'FINALIZED', 'FAILED'] as const) {
      const gates = gateActions(view({ state, available_actions: [] }))
      for (const action of ALL_ACTIONS) {
        assert.equal(gates[action].enabled, false, `${action} enabled on a ${state} case`)
        assert.equal(gates[action].permittedByState, false)
        assert.match(gates[action].blockedReason ?? '', new RegExp(state))
      }
    }
  })

  it('names the state, not a permission, when the state is what closed the gate', () => {
    // Defect 3: the UI said "Override requires senior-reviewer authority" for what was
    // in fact a state refusal — a permission the code had not consulted.
    const gates = gateActions(view({ state: 'FINALIZED' as CaseState, available_actions: [] }))
    const reason = gates.OVERRIDE_RECOMMENDATION.blockedReason ?? ''
    assert.match(reason, /not open for review/)
    assert.doesNotMatch(reason, /permission|authority|senior/i)
  })

  it('reports state before authority when both gates are closed', () => {
    // On a case nobody could act on, "you lack a permission" is true but misleading.
    const gates = gateActions(
      view({ state: 'FAILED' as CaseState, available_actions: [], may_override: false }),
    )
    assert.match(gates.OVERRIDE_RECOMMENDATION.blockedReason ?? '', /not open for review/)
  })
})

describe('authority gate', () => {
  it('mirrors the per-action permission table in app/case/review.py', () => {
    // REQUEST_INFO deliberately needs no FINALIZE_CASE: returning a case to the
    // submitter does not dispose of it. A console that gated all three identically
    // would hide an action a plain reviewer may take.
    const gates = gateActions(view({ may_finalize: false, may_override: false }))
    assert.equal(gates.REQUEST_INFORMATION.enabled, true)
    assert.equal(gates.ACCEPT_RECOMMENDATION.enabled, false)
    assert.equal(gates.OVERRIDE_RECOMMENDATION.enabled, false)
  })

  it('blocks override for a reviewer without OVERRIDE_RECOMMENDATION', () => {
    const gates = gateActions(view({ may_override: false }))
    assert.equal(gates.OVERRIDE_RECOMMENDATION.enabled, false)
    assert.equal(gates.OVERRIDE_RECOMMENDATION.permittedByState, true)
    assert.deepEqual(gates.OVERRIDE_RECOMMENDATION.missingPermissions, ['OVERRIDE_RECOMMENDATION'])
    // Accept and request-info are unaffected — one missing permission is not a lockout.
    assert.equal(gates.ACCEPT_RECOMMENDATION.enabled, true)
    assert.equal(gates.REQUEST_INFORMATION.enabled, true)
  })

  it('enables override for a reviewer who does hold it', () => {
    // Defect 2 in its plainest form: this was false for everyone, because the client
    // tested for a token ('OVERRIDE') the server never emits.
    assert.equal(gateActions(view()).OVERRIDE_RECOMMENDATION.enabled, true)
  })

  it('blocks everything for a read-only reviewer', () => {
    const gates = gateActions(
      view({ may_review: false, may_override: false, may_finalize: false }),
    )
    for (const action of ALL_ACTIONS) {
      assert.equal(gates[action].enabled, false, `${action} enabled without REVIEW_CASE`)
      assert.ok(gates[action].missingPermissions.includes('REVIEW_CASE'))
      assert.match(gates[action].blockedReason ?? '', /REVIEW_CASE/)
    }
  })

  it('lists every missing permission, not just the first', () => {
    const gates = gateActions(view({ may_review: false, may_finalize: false }))
    assert.deepEqual(gates.ACCEPT_RECOMMENDATION.missingPermissions, [
      'REVIEW_CASE',
      'FINALIZE_CASE',
    ])
  })
})

describe('exact token matching', () => {
  it('does not treat a short token as the action it resembles', () => {
    // The defect, pinned: `['OVERRIDE']` must not enable OVERRIDE_RECOMMENDATION, and a
    // server that started sending short tokens must fail loudly rather than silently.
    const gates = gateActions(
      view({ available_actions: ['ACCEPT', 'OVERRIDE', 'REQUEST_INFO'] as unknown as AvailableAction[] }),
    )
    for (const action of ALL_ACTIONS) {
      assert.equal(gates[action].permittedByState, false, `${action} matched a short token`)
    }
  })

  it('gates each action independently on its own token', () => {
    const gates = gateActions(view({ available_actions: ['REQUEST_INFORMATION'] }))
    assert.equal(gates.REQUEST_INFORMATION.enabled, true)
    assert.equal(gates.ACCEPT_RECOMMENDATION.enabled, false)
    assert.equal(gates.OVERRIDE_RECOMMENDATION.enabled, false)
  })

  it('covers exactly the three server actions and no more', () => {
    assert.deepEqual(Object.keys(gateActions(view())).sort(), [...ALL_ACTIONS].sort())
  })
})

describe('required free text', () => {
  it('requires text for the two actions whose bodies are min_length=1', () => {
    // OverrideRequest.rationale and RequestInformationRequest.requested_information.
    // AcceptRequest.comment is optional.
    assert.equal(requiresText('OVERRIDE_RECOMMENDATION'), true)
    assert.equal(requiresText('REQUEST_INFORMATION'), true)
    assert.equal(requiresText('ACCEPT_RECOMMENDATION'), false)
  })
})

describe('the gate is advisory, not an authorization rule', () => {
  it('reads every decision from the server response', () => {
    // Nothing may be derived from a role name, an id or a qualification. Flipping only
    // the server-reported flags must flip the outcome, with no other input in play.
    const permitted = gateActions(view())
    const refused = gateActions(view({ may_override: false }))
    assert.notEqual(
      permitted.OVERRIDE_RECOMMENDATION.enabled,
      refused.OVERRIDE_RECOMMENDATION.enabled,
    )
  })

  it('accepts a full ReviewCase without needing fields it must not read', () => {
    // Typing guard: `gateActions` takes only state, available_actions and the may_*
    // flags. A qualification string is not in its input type at all, so it cannot
    // become an authorization input by accident (OD-43).
    const full: Pick<ReviewCase, 'state' | 'available_actions' | 'may_review' | 'may_override' | 'may_finalize'> =
      view() as GateInput
    assert.equal(gateActions(full).ACCEPT_RECOMMENDATION.enabled, true)
  })
})
