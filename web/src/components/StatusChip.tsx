import { humanize } from '../lib/format'

const TONE: Record<string, string> = {
  CREATED: 'chip-neutral',
  SUBMITTED: 'chip-info',
  RECOMMENDATION_READY: 'chip-info',
  HUMAN_REVIEW: 'chip-amber',
  FINAL_INFO: 'chip-amber',
  CLOSED: 'chip-success',
}

export function StatusChip({ state }: { state: string }) {
  return <span className={`chip ${TONE[state] ?? 'chip-neutral'}`}>{humanize(state)}</span>
}