/**
 * Regression tests for case-state presentation (defect 1).
 *
 * The defect was that four of the seven server states had no entry and fell through to
 * a neutral grey chip — so a **FAILED** case rendered as unremarkable. These tests pin
 * totality and the two distinctions that carry meaning: failure must not read as
 * success, and an unknown state must not read as either.
 */
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { STATE_PRESENTATION, presentState } from './lifecycle.ts'
import type { CaseState } from './types.ts'

/** The server's lifecycle, from `app/case/lifecycle.py:CaseState`. */
const SERVER_STATES: CaseState[] = [
  'RECEIVED',
  'PROCESSING',
  'RECOMMENDATION_READY',
  'NEEDS_INFO',
  'HUMAN_REVIEW',
  'FINALIZED',
  'FAILED',
]

/** Names the previous build declared that the server cannot emit. */
const NAMES_THE_SERVER_NEVER_EMITS = ['CREATED', 'SUBMITTED', 'FINAL_INFO', 'CLOSED']

describe('the presentation table', () => {
  it('is total over the server lifecycle', () => {
    assert.deepEqual(Object.keys(STATE_PRESENTATION).sort(), [...SERVER_STATES].sort())
  })

  it('gives every state a label, a tone and a meaning', () => {
    for (const state of SERVER_STATES) {
      const p = STATE_PRESENTATION[state]
      assert.ok(p.label.length > 0, `${state} has no label`)
      assert.ok(p.tone.startsWith('chip-'), `${state} has no chip tone`)
      assert.ok(p.meaning.length > 20, `${state} has no meaning worth showing`)
    }
  })

  it('marks exactly the two terminal states terminal', () => {
    const terminal = SERVER_STATES.filter((s) => STATE_PRESENTATION[s].terminal)
    assert.deepEqual(terminal.sort(), ['FAILED', 'FINALIZED'])
  })
})

describe('states that must not be confusable', () => {
  it('does not render FAILED as neutral or successful', () => {
    // The defect, precisely: FAILED fell through to `chip-neutral`.
    const failed = STATE_PRESENTATION.FAILED
    assert.equal(failed.tone, 'chip-danger')
    assert.notEqual(failed.tone, 'chip-neutral')
    assert.notEqual(failed.tone, 'chip-success')
  })

  it('says a failed run is not a clinical outcome', () => {
    // Fail-closed routes toward the human, never toward a denial. A reviewer must not
    // read an infrastructure failure as a finding about coverage.
    assert.match(STATE_PRESENTATION.FAILED.meaning, /never a clinical one|not a clinical/i)
    assert.match(STATE_PRESENTATION.FAILED.meaning, /covered/i)
  })

  it('does not render FINALIZED and RECOMMENDATION_READY alike', () => {
    // A recommendation is not a disposition; the lifecycle has no edge from one to the
    // other without a person, and the two must not look the same.
    assert.notEqual(
      STATE_PRESENTATION.RECOMMENDATION_READY.tone,
      STATE_PRESENTATION.FINALIZED.tone,
    )
    assert.match(STATE_PRESENTATION.RECOMMENDATION_READY.meaning, /not a disposition/i)
  })

  it('explains that a RECEIVED case has not run, rather than implying a fault', () => {
    // `POST /cases` accepts and does not execute. Without this the empty recommendation
    // panel reads as a broken console.
    assert.match(STATE_PRESENTATION.RECEIVED.meaning, /nothing has run|not.*run/i)
    assert.match(STATE_PRESENTATION.RECEIVED.meaning, /separate/i)
  })
})

describe('presentState', () => {
  it('returns the table entry for every known state', () => {
    for (const state of SERVER_STATES) {
      assert.equal(presentState(state), STATE_PRESENTATION[state])
    }
  })

  it('flags an unrecognised state loudly instead of greying it out', () => {
    // Including the four names the previous build invented: if a build ever declares
    // them again, they must surface as a contract disagreement, not as a quiet chip.
    for (const name of [...NAMES_THE_SERVER_NEVER_EMITS, 'WAT']) {
      const p = presentState(name)
      assert.equal(p.tone, 'chip-danger', `${name} was rendered quietly`)
      assert.match(p.meaning, /disagree/i)
      assert.equal(p.label, name, 'an unknown state was relabelled into something familiar')
    }
  })
})
