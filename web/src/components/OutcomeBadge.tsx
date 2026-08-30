/** Outcome tokens rendered neutrally. MEDD has no "no/deny" model-output schema. */
export function OutcomeBadge({ outcome }: { outcome?: string | null }) {
  if (!outcome) return null
  const up = String(outcome).toUpperCase()
  let tone = 'chip-neutral'
  if (up.includes('NEEDS') || up.includes('INSUFFICIENT') || up.includes('INFORMATION')) tone = 'chip-amber'
  if (up.includes('DENY') || up.includes('DENIED') || up.includes('ERROR') || up.includes('FAIL')) tone = 'chip-danger'
  if (up.includes('APPROV') || up.includes('COVERED') || up.includes('CONFIRM') || up.includes('CLOSED')) tone = 'chip-success'
  return <span className={`chip ${tone}`}>{String(outcome)}</span>
}