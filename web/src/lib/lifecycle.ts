/**
 * How each case state is presented, and what it means for the reviewer.
 *
 * ## Why a total table rather than a lookup with a fallback
 *
 * The previous `StatusChip` held a partial `Record<string, string>` keyed on state names
 * that the server does not emit, and fell back to a neutral grey chip. Four of the seven
 * real states hit that fallback, so **`FAILED` rendered as unremarkable** — a run that
 * could not complete looked like a run that had merely not finished. This table is total
 * over `CaseState`, and TypeScript's exhaustiveness check on the `Record<CaseState, …>`
 * means a state added to the server enum cannot be silently absent here.
 *
 * ## `meaning` is not decoration
 *
 * `POST /cases` accepts a case; it does **not** execute the pipeline (see
 * `app/api/v1/routes.py:submit_case`, and `docs/architecture/application-lifecycle.md`).
 * A submitter who saw only the word "RECEIVED" would reasonably read the empty
 * recommendation panel as a system fault. The sentence attached to each state says what
 * the system is actually doing, so an architecture that separates submission from
 * execution reads as deliberate rather than broken.
 */
import type { CaseState } from './types'

export interface StatePresentation {
  /** Sentence-case label for display. */
  readonly label: string
  /** Chip class from `index.css`. */
  readonly tone: 'chip-neutral' | 'chip-info' | 'chip-amber' | 'chip-danger' | 'chip-success'
  /** What this state means, in the reviewer's terms. */
  readonly meaning: string
  /** Terminal states have no successors — `app/case/lifecycle.py:TERMINAL_STATES`. */
  readonly terminal: boolean
}

export const STATE_PRESENTATION: Record<CaseState, StatePresentation> = {
  RECEIVED: {
    label: 'Received',
    tone: 'chip-neutral',
    meaning:
      'Accepted and persisted. Nothing has run yet — submission and execution are separate steps in this system, so a case waits here until a run is started.',
    terminal: false,
  },
  PROCESSING: {
    label: 'Processing',
    tone: 'chip-info',
    meaning: 'The pipeline is executing. No recommendation exists yet.',
    terminal: false,
  },
  RECOMMENDATION_READY: {
    label: 'Recommendation ready',
    tone: 'chip-info',
    meaning:
      'The engine produced a recommendation. This is not a disposition, and this case is not yet open for review.',
    terminal: false,
  },
  NEEDS_INFO: {
    label: 'Needs info',
    tone: 'chip-amber',
    meaning:
      'A question was put to the submitter. The case returns to processing once they answer.',
    terminal: false,
  },
  HUMAN_REVIEW: {
    label: 'Human review',
    tone: 'chip-amber',
    meaning: 'Routed to a person. This case is open for review.',
    terminal: false,
  },
  FINALIZED: {
    label: 'Finalized',
    tone: 'chip-success',
    meaning:
      'A named reviewer acted. Terminal — a finalised case cannot be reopened, and a reviewer who changes their mind files a new review rather than editing this one.',
    terminal: true,
  },
  FAILED: {
    label: 'Failed',
    tone: 'chip-danger',
    meaning:
      'The run could not complete. This is an infrastructure outcome and never a clinical one — it says nothing about whether the service is covered.',
    terminal: true,
  },
}

/** Presentation for a state, tolerating an unknown value from an older/newer server. */
export function presentState(state: string): StatePresentation {
  const known = STATE_PRESENTATION[state as CaseState]
  if (known) return known
  // Loud rather than grey. An unrecognised state means this build and the server
  // disagree about the lifecycle, which is exactly the defect this module exists to
  // stop being invisible.
  return {
    label: state,
    tone: 'chip-danger',
    meaning: `Unrecognised case state "${state}". This console and the API disagree about the case lifecycle; do not act on this case until that is resolved.`,
    terminal: false,
  }
}
