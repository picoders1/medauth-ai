/**
 * Whether a review action can be taken, and if not, which gate stopped it.
 *
 * ## Two gates, reported separately
 *
 * The server checks a review action against two independent things:
 *
 *  1. **State** — `app/case/review.py` refuses any action unless the case is in
 *     `HUMAN_REVIEW`. That is what `available_actions` publishes.
 *  2. **Authority** — `HumanReviewService.record` calls `Principal.require()` for each
 *     permission the action needs (`app/case/review.py:111-116`). That is what the
 *     `may_*` flags publish.
 *
 * The previous UI had neither. It tested `available_actions.includes('OVERRIDE')` — a
 * token the server never emits, so override was permanently disabled — and it told the
 * reviewer that override "requires senior-reviewer authority", attributing a state
 * refusal to a permission the code had not consulted. Accept and request-info consulted
 * nothing at all and stayed clickable on a finalised case.
 *
 * ## This module decides nothing
 *
 * Every value below is read from the server's own response. There is no client-side
 * permission rule here, and there must never be one: `HumanReviewService.record`
 * re-checks each permission before writing, so a client that ignored this file entirely
 * would be refused identically. This exists so the UI can *explain* the refusal in
 * advance instead of presenting a button that will 403.
 */
import type { AvailableAction, ReviewCase } from './types'

/** The permissions each action needs — mirrors `app/case/review.py:111-116`. */
const REQUIRED_PERMISSIONS: Record<AvailableAction, readonly (keyof ReviewerPermissions)[]> = {
  // HumanReviewAction.APPROVE: REVIEW_CASE, and FINALIZE_CASE because it disposes of
  // the case ("if action is not REQUEST_INFO").
  ACCEPT_RECOMMENDATION: ['may_review', 'may_finalize'],
  // Additionally OVERRIDE_RECOMMENDATION: disagreeing with the engine is a distinct
  // authority from agreeing with it.
  OVERRIDE_RECOMMENDATION: ['may_review', 'may_override', 'may_finalize'],
  // Returns the case to the submitter rather than disposing of it, so no FINALIZE_CASE.
  REQUEST_INFORMATION: ['may_review'],
}

/** Human-readable names for the refusal message, keyed by the flag. */
const PERMISSION_LABEL: Record<keyof ReviewerPermissions, string> = {
  may_review: 'REVIEW_CASE',
  may_override: 'OVERRIDE_RECOMMENDATION',
  may_finalize: 'FINALIZE_CASE',
}

export type ReviewerPermissions = Pick<ReviewCase, 'may_review' | 'may_override' | 'may_finalize'>

export interface ActionGate {
  /** The case's state permits this action (it is in `available_actions`). */
  readonly permittedByState: boolean
  /** This reviewer holds every permission the action needs. */
  readonly permittedByAuthority: boolean
  /** Both gates open. The only condition under which the control may be enabled. */
  readonly enabled: boolean
  /**
   * Why not, in the reviewer's terms — `null` when enabled. State is reported before
   * authority: on a case that is not open for review, "you lack a permission" would be
   * true but misleading, since no reviewer of any authority could act on it.
   */
  readonly blockedReason: string | null
  /** Permissions the action needs that this reviewer does not hold. */
  readonly missingPermissions: readonly string[]
}

export type ActionGates = Record<AvailableAction, ActionGate>

/**
 * Gate every review action for one case and one reviewer.
 *
 * `stateMeaning` is the sentence from `lifecycle.ts`, folded into the state refusal so
 * the reason names the actual state rather than saying "unavailable".
 */
export function gateActions(
  view: Pick<ReviewCase, 'available_actions' | 'state'> & ReviewerPermissions,
  stateMeaning?: string,
): ActionGates {
  const gates = {} as Record<AvailableAction, ActionGate>

  for (const action of Object.keys(REQUIRED_PERMISSIONS) as AvailableAction[]) {
    const permittedByState = view.available_actions.includes(action)
    const missing = REQUIRED_PERMISSIONS[action]
      .filter((flag) => !view[flag])
      .map((flag) => PERMISSION_LABEL[flag])
    const permittedByAuthority = missing.length === 0

    let blockedReason: string | null = null
    if (!permittedByState) {
      blockedReason =
        `This case is ${view.state} and is not open for review.` +
        (stateMeaning ? ` ${stateMeaning}` : '')
    } else if (!permittedByAuthority) {
      blockedReason = `Your reviewer identity does not hold ${missing.join(' and ')}.`
    }

    gates[action] = {
      permittedByState,
      permittedByAuthority,
      enabled: permittedByState && permittedByAuthority,
      blockedReason,
      missingPermissions: missing,
    }
  }

  return gates
}

/**
 * Whether an override's rationale is present. `OverrideRequest.rationale` is
 * `min_length=1` and `app/case/review.py:_REQUIRE_RATIONALE` refuses an override
 * without one; the same is true of `requested_information` on a request-info.
 */
export function requiresText(action: AvailableAction): boolean {
  return action === 'OVERRIDE_RECOMMENDATION' || action === 'REQUEST_INFORMATION'
}
