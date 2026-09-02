import type { ReactNode } from 'react'
import { BrainCircuit, ScrollText, ShieldAlert } from 'lucide-react'
import type { AuditTrail, ReviewCase } from '../lib/types'
import { fmt } from '../lib/format'
import { presentState } from '../lib/lifecycle'
import { OutcomeCard } from './ReviewTab'

/**
 * The engine's draft, and the trace behind it.
 *
 * The routing explanation comes FIRST and the recommendation second. This tab used to
 * be ordered the other way — draft, then trace — which is the anchoring pattern R-04
 * names and the exact ordering the Jinja reviewer page is built to avoid
 * (`app/api/templates/case_detail.html`). A reviewer must be able to read why the case
 * is here before they read what the system proposed, on every surface that shows both.
 */
export function RecommendationTab({ view }: { view: ReviewCase | null }) {
  if (!view) {
    return (
      <div className="panel p-6 text-sm text-[#8fa8c4]">
        No reviewer context available — add a bearer token in Settings.
      </div>
    )
  }
  const state = presentState(view.state)
  return (
    <div className="space-y-5">
      <Panel title="Why this case is here" icon={<BrainCircuit size={15} />}>
        <p className="text-sm text-[#c7d2e8]">{view.routing_explanation || '—'}</p>
        <p className="mt-2 text-xs text-[#8fa8c4]">{state.meaning}</p>
      </Panel>

      {view.provider_failure_kind && (
        <Panel title="Provider failure" icon={<ShieldAlert size={15} />}>
          <p className="mono text-sm text-white">{view.provider_failure_kind}</p>
          <p className="mt-1.5 text-sm text-[#c7d2e8]">
            This is an infrastructure failure, not a finding about the clinical facts. It says
            nothing about whether the requested service is covered.
          </p>
        </Panel>
      )}

      <OutcomeCard
        label="AI-generated recommendation — NOT a decision"
        out={view.ai_recommendation ?? ''}
        tone="ai"
        meta={
          view.recommended_at ? (
            <p className="mt-1.5 text-xs text-[#8fa8c4]">Produced {fmt(view.recommended_at)}</p>
          ) : null
        }
      />

      <Panel title="Engine trace" icon={<BrainCircuit size={15} />}>
        <Grid
          rows={[
            ['Decision rule', view.decision_rule],
            ['Resolution state', view.resolution_state],
            ['Resolution reason', view.resolution_reason],
            ['Contradiction state', view.contradiction_state],
            ['Policy type', view.policy_type],
            ['Policy id', view.policy_id],
            ['Policy version', view.policy_version],
            [
              'Confidence',
              view.confidence_state === 'UNCALIBRATED'
                ? 'UNCALIBRATED — no calibrated probability exists for this system'
                : view.confidence_state,
            ],
            ['Abstention reason', view.abstention_reason],
          ]}
        />
      </Panel>
    </div>
  )
}

/**
 * Evidence recorded for the run. `criterion_ids` says which criterion each chunk was
 * retrieved for; dropping it (as this tab previously did) leaves a list of opaque chunk
 * ids that a reviewer cannot connect to anything they are being asked to judge.
 */
export function EvidenceTab({ view }: { view: ReviewCase | null }) {
  if (!view) {
    return (
      <div className="panel p-6 text-sm text-[#8fa8c4]">
        No reviewer context available — add a bearer token in Settings.
      </div>
    )
  }
  if (view.evidence.length === 0) {
    return (
      <div className="panel p-6 text-sm text-[#8fa8c4]">
        No evidence was recorded — this case did not reach retrieval.
      </div>
    )
  }
  return (
    <div className="space-y-4">
      <p className="text-xs text-[#8fa8c4]">
        Read from the run's own record. Retrieval is <strong>not</strong> re-executed when this
        page loads — that would show today's corpus for an earlier decision.
      </p>
      <div className="space-y-2.5">
        {view.evidence.map((e, i) => (
          <div key={i} className="panel px-4 py-3">
            <div className="flex flex-wrap items-center gap-3">
              <ScrollText size={14} className="shrink-0 text-[#5b6b8a]" />
              <span className="mono text-sm text-[#c7d2e8]">{e.chunk_id}</span>
              <span className="ml-auto text-xs text-[#8fa8c4]">{e.stage}</span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="label mb-0">Criteria</span>
              {e.criterion_ids.length > 0 ? (
                e.criterion_ids.map((c) => (
                  <span key={c} className="chip chip-neutral mono">
                    {c}
                  </span>
                ))
              ) : (
                <span className="text-xs text-[#8fa8c4]">—</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function AuditTab({ audit }: { audit: AuditTrail | null }) {
  if (!audit || audit.events.length === 0) {
    return <div className="panel p-6 text-sm text-[#8fa8c4]">No audit trail.</div>
  }
  return (
    <div className="space-y-3">
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
      <p className="text-xs text-[#8fa8c4]">
        Append-only. Every transition writes an event in the same transaction as the state change.
      </p>
    </div>
  )
}

function Panel({ title, icon, children }: { title: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel p-4">
      <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[#8fa8c4]">
        {icon} {title}
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
