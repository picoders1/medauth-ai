import type { ReactNode } from 'react'
import { BrainCircuit } from 'lucide-react'
import type { AuditTrail, ReviewCase } from '../lib/types'
import { fmt } from '../lib/format'
import { OutcomeCard } from './ReviewTab'

export function RecommendationTab({ view }: { view: ReviewCase | null }) {
  if (!view) return <div>No recommendation data.</div>
  return (
    <div className="space-y-5">
      <OutcomeCard label="AI-generated recommendation — NOT a decision" out={view.ai_recommendation ?? ''} tone="ai" />

      <Panel title="Engine trace">
        <Grid
          rows={[
            ['Decision rule', view.decision_rule],
            ['Resolution state', view.resolution_state],
            ['Resolution reason', view.resolution_reason],
            ['Contradiction state', view.contradiction_state],
            ['Policy type', view.policy_type],
            ['Policy id', view.policy_id],
            ['Policy version', view.policy_version],
            ['Confidence', view.confidence_state],
            ['Abstention reason', view.abstention_reason],
          ]}
        />
      </Panel>
      {view.provider_failure_kind && (
        <Panel title="Provider note">
          <p className="text-sm text-[#c7d2e8]">{view.provider_failure_kind}</p>
        </Panel>
      )}
    </div>
  )
}

export function EvidenceTab({ view }: { view: ReviewCase | null }) {
  if (!view) return <div>No evidence.</div>
  if (view.evidence.length === 0) {
    return (
      <div className="panel p-6 text-sm text-[#8fa8c4]">
        No evidence was recorded for this case. This is expected when the case was not assessed.
      </div>
    )
  }
  return (
    <div className="space-y-2.5">
      {view.evidence.map((e, i) => (
        <div key={i} className="panel flex flex-wrap items-center gap-3 px-4 py-3">
          <span className="label mb-0 w-16">chunk</span>
          <span className="mono text-sm text-[#c7d2e8]">{e.chunk_id}</span>
          <span className="ml-auto text-xs text-[#8fa8c4]">{e.stage}</span>
        </div>
      ))}
    </div>
  )
}

export function AuditTab({ audit }: { audit: AuditTrail | null }) {
  if (!audit || audit.events.length === 0) return <div>No audit trail.</div>
  return (
    <ul className="space-y-1.5">
      {audit.events.map((e, i) => (
        <li key={i} className="panel flex flex-wrap items-center gap-3 px-4 py-2.5 text-sm">
          <span className="mono text-[#8fa8c4]">{fmt(e.created_at)}</span>
          <span className="chip chip-neutral">{e.stage || e.event}</span>
          {e.outcome && <span className="text-[#c7d2e8]">{e.outcome}</span>}
          {e.correlation_id && (
            <span className="mono ml-auto text-xs text-[#8fa8c4]">{e.correlation_id}</span>
          )}
        </li>
      ))}
    </ul>
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel p-4">
      <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[#8fa8c4]">
        <BrainCircuit size={15} /> {title}
      </h3>
      {children}
    </section>
  )
}

function Grid({ rows }: { rows: [string, string | null | undefined][] }) {
  return (
    <dl className="grid gap-x-6 gap-y-2.5 sm:grid-cols-2">
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt className="label">{k}</dt>
          <dd className="text-sm text-[#c7d2e8]">{v || '—'}</dd>
        </div>
      ))}
    </dl>
  )
}