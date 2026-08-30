import { useState } from 'react'
import { Check, CircleAlert, ClipboardList, Clock, History, KeyRound, User, X } from 'lucide-react'
import type { useSession } from '../lib/auth'
import type { ReviewCase } from '../lib/types'
import { OutcomeBadge } from '../components/OutcomeBadge'
import { fmt } from '../lib/format'

export function ReviewTab({
  session,
  id,
  view,
  onChanged,
}: {
  session: ReturnType<typeof useSession>
  id: string
  view: ReviewCase | null
  onChanged: () => void
}) {
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <div className="space-y-5 lg:col-span-2">
        {!view ? (
          <div className="panel p-6 text-sm text-[#8fa8c4]">
            No reviewer context available — add a bearer token in Settings to see the review view.
          </div>
        ) : (
          <>
            <Panel title="Routing & context" icon={<ClipboardList size={15} />}>
              {view.routing_explanation ? (
                <p className="text-sm text-[#c7d2e8]">{view.routing_explanation}</p>
              ) : (
                <p className="text-sm text-[#8fa8c4]">No routing note recorded.</p>
              )}
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <KV k="Decision rule" v={view.decision_rule ?? '—'} mono />
                <KV k="Resolution" v={view.resolution_state ?? '—'} />
                <KV k="Policy" v={[view.policy_type, view.policy_id].filter(Boolean).join(' ') || '—'} mono />
                <KV k="Confidence" v={view.confidence_state ?? '—'} />
              </div>
            </Panel>

            <OutcomeCard
              label="AI-generated recommendation — not a decision"
              out={view.ai_recommendation ?? ''}
              tone="ai"
            />

            {view.human_disposition ? (
              <OutcomeCard
                label="Human disposition"
                out={view.human_disposition}
                tone="human"
                meta={<HumanMeta view={view} />}
              />
            ) : (
              <div className="panel border-l-4 border-l-[#3b82f6] px-4 py-3 text-sm text-[#c7d2e8]">
                No human decision recorded yet.
              </div>
            )}

            {view.contradiction_state && (
              <div className="panel flex items-center gap-2 border-[#7c3aed]/40 px-4 py-2.5 text-sm text-[#c4b5fd]">
                <CircleAlert size={15} /> Contradiction detected: {view.contradiction_state}
              </div>
            )}

            <ReviewActions session={session} id={id} view={view} onDone={onChanged} />
          </>
        )}
      </div>

      <aside className="space-y-5">
        <Panel title="Reviewer" icon={<User size={15} />}>
          <KV k="Identity" v={view?.reviewer_principal_id ?? '—'} mono />
          <KV k="Qualification" v={view?.qualification_state ?? '—'} />
          {view?.qualification_notice && (
            <p className="mt-2 text-xs leading-relaxed text-[#8fa8c4]">{view.qualification_notice}</p>
          )}
        </Panel>
        {view && view.history.length > 0 && (
          <Panel title="History" icon={<History size={15} />}>
            <ul className="space-y-2.5">
              {view.history.map((h, i) => (
                <li key={i} className="text-xs">
                  <div className="flex items-center gap-2">
                    <OutcomeBadge outcome={h.action} />
                    {h.outcome && <OutcomeBadge outcome={h.outcome} />}
                    <span className="ml-auto shrink-0 text-[#8fa8c4]">{fmt(h.created_at)}</span>
                  </div>
                  {h.rationale && <p className="mt-1 text-[#9aa8c4]">{h.rationale}</p>}
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </aside>
    </div>
  )
}

function HumanMeta({ view }: { view: ReviewCase }) {
  return (
    <div className="flex items-center gap-4 text-xs text-[#8fa8c4]">
      <span className="flex items-center gap-1">
        <User size={12} /> {view.disposition_by ?? '—'}
      </span>
      <span className="flex items-center gap-1">
        <Clock size={12} /> {view.disposition_at ? fmt(view.disposition_at) : '—'}
      </span>
    </div>
  )
}

function Panel({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="panel p-4">
      <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[#8fa8c4]">
        {icon} {title}
      </h3>
      {children}
    </section>
  )
}

function KV({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div>
      <div className="label">{k}</div>
      <div className={`text-sm text-[#c7d2e8] ${mono ? 'mono' : ''}`}>{v || '—'}</div>
    </div>
  )
}

export function OutcomeCard({ label, out, tone, meta }: { label: string; out: string; tone: 'ai' | 'human'; meta?: React.ReactNode }) {
  const border = tone === 'human' ? 'border-l-[#2563eb]' : 'border-l-[#7c3aed]'
  return (
    <div className={`panel border-l-4 ${border} px-4 py-3`}>
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs uppercase tracking-wide text-[#8fa8c4]">{label}</div>
        <OutcomeBadge outcome={out} />
      </div>
      <p className="mt-1.5 text-sm font-medium text-white">{out || '—'}</p>
      {meta}
    </div>
  )
}

function ReviewActions({
  session,
  id,
  view,
  onDone,
}: {
  session: ReturnType<typeof useSession>
  id: string
  view: ReviewCase
  onDone: () => void
}) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [overrideOut, setOverrideOut] = useState<'APPROVED' | 'DENIED'>('DENIED')

  const canOverride = view.available_actions.includes('OVERRIDE')
  const qualification = view.reviewer_qualification ?? ''

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setErr(null)
    try {
      await fn()
      onDone()
    } catch (x) {
      setErr((x as Error)?.message ?? 'action failed')
    } finally {
      setBusy(false)
    }
  }

  if (!session.creds.bearerToken) {
    return (
      <div className="panel flex items-center gap-3 border-[#7c3aed]/40 px-5 py-4 text-sm text-[#c4b5fd]">
        <KeyRound size={15} /> Review actions need a bearer token — add it in Settings.
      </div>
    )
  }

  return (
    <div className="panel space-y-3 p-5">
      <div className="text-sm font-semibold text-white">Human decision</div>
      <textarea
        className="field"
        rows={3}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder={canOverride ? 'Comment — required for an override' : 'Comment (optional)'}
      />
      {canOverride && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="label mb-0">Override outcome:</span>
          {(['APPROVED', 'DENIED'] as const).map((o) => (
            <button
              key={o}
              type="button"
              onClick={() => setOverrideOut(o)}
              className={`chip ${overrideOut === o ? (o === 'APPROVED' ? 'chip-success' : 'chip-danger') : 'chip-neutral'}`}
            >
              {o === 'APPROVED' ? 'Approve' : 'Deny'}
            </button>
          ))}
        </div>
      )}
      {err && <p className="text-sm text-[#fca5a5]">{err}</p>}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn btn-success"
          disabled={busy}
          onClick={() => run(() => session.client.accept(id, comment.trim() || undefined, qualification))}
        >
          <Check size={15} /> Accept
        </button>
        <button
          type="button"
          className="btn btn-amber"
          disabled={busy}
          onClick={() =>
            run(() => session.client.requestInfo(id, comment.trim() || 'Additional information is required.', qualification))
          }
        >
          <ClipboardList size={15} /> Request info
        </button>
        <button
          type="button"
          className="btn btn-danger"
          disabled={busy || !canOverride}
          onClick={() =>
            run(() => {
              if (!comment.trim()) return Promise.reject(new Error('rationale is required for an override'))
              return session.client.override(id, overrideOut, comment.trim(), qualification)
            })
          }
        >
          <X size={15} /> Override
        </button>
      </div>
      {!canOverride && <p className="text-xs text-[#8fa8c4]">Override requires senior-reviewer authority.</p>}
    </div>
  )
}