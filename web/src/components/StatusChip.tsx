import { presentState } from '../lib/lifecycle'

/**
 * A case's state, from the total table in `lib/lifecycle.ts`.
 *
 * This component previously held its own partial map keyed on state names the server
 * does not emit (`CREATED`, `SUBMITTED`, `FINAL_INFO`, `CLOSED`), so `FAILED`,
 * `FINALIZED`, `NEEDS_INFO`, `PROCESSING` and `RECEIVED` all fell through to a neutral
 * grey chip. The mapping now lives in one place beside the lifecycle it mirrors.
 */
export function StatusChip({ state }: { state: string }) {
  const presentation = presentState(state)
  return (
    <span className={`chip ${presentation.tone}`} title={presentation.meaning}>
      {presentation.label}
    </span>
  )
}
