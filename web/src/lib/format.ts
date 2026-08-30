export function fmt(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

export function humanize(state: string): string {
  return state.replace(/_/g, ' ').toLowerCase()
}