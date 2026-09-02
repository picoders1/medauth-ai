import { useState } from 'react'
import {
  Check,
  CircleAlert,
  ClipboardList,
  Clock,
  History,
  KeyRound,
  ShieldAlert,
  User,
  X,
} from 'lucide-react'
import type { useSession } from '../lib/auth'
import type { AvailableAction, ReviewCase } from '../lib/types'
import { OutcomeBadge } from '../components/OutcomeBadge'
import { fmt } from '../lib/format'
import { presentState } from '../lib/lifecycle'
import { gateActions, type ActionGates } from '../lib/actions'
import { ApiHttpError } from '../api/client'

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
            {/*
              ORDER IS A SAFETY PROPERTY, not a layout choice. "Why this case is in front
              of you" comes before "what the engine proposed", so a reviewer reads the
              question before the suggested answer. Anchoring on a displayed
              recommendation is R-04, and it is the reason the Jinja reviewer page
              (app/api/templates/case_detail.html) is ordered the same way.
            */}
            <Panel title="Why this case needs a person" icon={<ClipboardList size={15} />}>
              {view.routing_explanation ? (
                <p className="text-sm text-[#c7d2e8]">{view.routing_explanation}</p>
              ) : (
                <p className="text-sm text-[#8fa8c4]">No routing note recorded.</p>
              )}
              <p className="mt-2 text-xs text-[#8fa8c4]">{presentState(view.state).meaning}</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <KV k="Decision rule" v={view.decision_rule ?? '—'} mono />
                <KV k="Resolution" v={view.resolution_state ?? '—'} />
                <KV k="Policy" v={[view.policy_type, view.policy_id].filter(Boolean).join(' ') || '—'} mono />
                <KV k="Confidence" v={view.confidence_state ?? '—'} />
              </div>
              {view.abstention_reason && (
                <p className="mt-3 text-xs text-[#8fa8c4]">
                  Abstention: <span className="mono text-[#c7d2e8]">{view.abstention_reason}</span>
                </p>
              )}
            </Panel>

            {view.provider_failure_kind && <ProviderFailureNotice kind={view.provider_failure_kind} />}

            <OutcomeCard
              label="AI-generated recommendation — not a decision"
              out={view.ai_recommendation ?? ''}
              tone="ai"
              meta={
                view.recommended_at ? (
                  <div className="mt-1.5 flex items-center gap-1 text-xs text-[#8fa8c4]">
                    <Clock size={12} /> Produced {fmt(view.recommended_at)}
                  </div>
                ) : null
              }
            />

            {view.human_disposition ? (
              <OutcomeCard
                label="Human disposition"
                out={view.human_disposition}
                tone="human"
                meta={<HumanMeta view={view} />}
              />
            ) : (
              <div className="panel border-l-4 border-l-[#3b82f6] px-4 py-3">
                <div className="text-xs uppercase tracking-wide text-[#8fa8c4]">Human disposition</div>
                <p className="mt-1.5 text-sm text-[#c7d2e8]">
                  No human decision has been recorded on this case.
                </p>
              </div>
            )}

            {view.contradiction_state && view.contradiction_state !== 'NONE' && (
              <div className="panel flex items-center gap-2 border-[#7c3aed]/40 px-4 py-2.5 text-sm text-[#c4b5fd]">
                <CircleAlert size={15} /> Contradiction analysis:{' '}
                <span className="mono">{view.contradiction_state}</span>
              </div>
            )}

            <ReviewActions session={session} id={id} view={view} onDone={onChanged} />
          </>
        )}
      </div>

      <aside className="space-y-5">
        <Panel title="Reviewer" icon={<User size={15} />}>
          <KV k="Identity" v={view?.reviewer_principal_id ?? '—'} mono />
          <div className="mt-2.5">
            <KV k="Qualification" v={view?.qualification_state ?? '—'} />
          </div>
          {view?.qualification_notice && (
            <p className="mt-2 text-xs leading-relaxed text-[#8fa8c4]">{view.qualification_notice}</p>
          )}
          {view && <GrantedPermissions view={view} />}
        </Panel>
        {view && view.history.length > 0 && (
          <Panel title="Previous human decisions" icon={<History size={15} />}>
            <ul className="space-y-3">
              {view.history.map((h, i) => (
                <li key={i} className="text-xs">
                  <div className="flex items-center gap-2">
                    <OutcomeBadge outcome={h.action} />
                    {h.outcome && <OutcomeBadge outcome={h.outcome} />}
                    <span className="ml-auto shrink-0 text-[#8fa8c4]">{fmt(h.created_at)}</span>
                  </div>
                  <div className="mt-1 text-[#8fa8c4]">
                    {h.reviewer_principal_id || '—'} · <IdentityModel model={h.identity_model} />
                  </div>
                  {h.rationale && <p className="mt-1 text-[#9aa8c4]">{h.rationale}</p>}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-[#8fa8c4]">
              Append-only. A later decision is added; it never replaces an earlier one.
            </p>
          </Panel>
        )}
      </aside>
    </div>
  )
}

/**
 * A provider failure is an infrastructure outcome, and the interface has to say so.
 *
 * The Jinja reviewer page carries this sentence, and the SPA previously rendered the
 * bare token under the heading "Provider note" — which invites a reviewer to read a
 * transport failure as a finding about the clinical facts. Fail-closed routes toward the
 * human, never toward a denial, and the reason it landed here must not be ambiguous.
 */
function ProviderFailureNotice({ kind }: { kind: string }) {
  return (
    <div className="panel border-l-4 border-l-[#b45309] px-4 py-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-[#fbbf24]">
        <ShieldAlert size={14} /> Provider failure
      </div>
      <p className="mono mt-1.5 text-sm text-white">{kind}</p>
      <p className="mt-1.5 text-sm text-[#c7d2e8]">
        This is an infrastructure failure, not a finding about the clinical facts. It says nothing
        about whether the requested service is covered.
      </p>
    </div>
  )
}

/**
 * `LEGACY_CALLER_SUPPLIED` means the reviewer identity on that row was asserted by the
 * calling system, not authenticated (OD-43). Rendering it identically to an
 * authenticated identity would misrepresent the audit trail in exactly the situation
 * the trail exists for.
 */
function IdentityModel({ model }: { model: string }) {
  if (model === 'LEGACY_CALLER_SUPPLIED') {
    return (
      <span className="text-[#fbbf24]">
        {model} — self-declared, not authenticated
      </span>
    )
  }
  return <span className="mono">{model}</span>
}

/** What this reviewer's token was granted. Reported by the API; enforced by the service. */
function GrantedPermissions({ view }: { view: ReviewCase }) {
  const granted: [string, boolean][] = [
    ['REVIEW_CASE', view.may_review],
    ['OVERRIDE_RECOMMENDATION', view.may_override],
    ['FINALIZE_CASE', view.may_finalize],
  ]
  return (
    <div className="mt-3 border-t border-[#1c2742] pt-3">
      <div className="label">Permissions granted</div>
      <ul className="space-y-1">
        {granted.map(([name, held]) => (
          <li key={name} className="flex items-center gap-1.5 text-xs">
            {held ? (
              <Check size={12} className="shrink-0 text-[#4ade80]" />
            ) : (
              <X size={12} className="shrink-0 text-[#5b6b8a]" />
            )}
            <span className={`mono ${held ? 'text-[#c7d2e8]' : 'text-[#5b6b8a]'}`}>{name}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs leading-relaxed text-[#8fa8c4]">
        Granted to the authenticated identity. A stated qualification grants none of these.
      </p>
    </div>
  )
}

function HumanMeta({ view }: { view: ReviewCase }) {
  return (
    <div className="mt-1.5 flex items-center gap-4 text-xs text-[#8fa8c4]">
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

export function OutcomeCard({
  label,
  out,
  tone,
  meta,
}: {
  label: string
  out: string
  tone: 'ai' | 'human'
  meta?: React.ReactNode
}) {
  const border = tone === 'human' ? 'border-l-[#2563eb]' : 'border-l-[#7c3aed]'
  return (
    <div className={`panel border-l-4 ${border} px-4 py-3`}>
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs uppercase tracking-wide text-[#8fa8c4]">{label}</div>
        <OutcomeBadge outcome={out} />
      </div>
      <p className="mt-1.5 text-sm font-medium text-white">{out || 'none produced'}</p>
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
  const [err, setErr] = useState<{ message: string; requestId?: string } | null>(null)
  const [overrideOut, setOverrideOut] = useState<'APPROVED' | 'DENIED'>('DENIED')

  // Both gates, both from the server: `available_actions` (state) and `may_*`
  // (authority). Nothing here derives a permission.
  const gates: ActionGates = gateActions(view, presentState(view.state).meaning)
  const qualification = view.reviewer_qualification ?? ''
  const text = comment.trim()

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setErr(null)
    try {
      await fn()
      onDone()
    } catch (x) {
      setErr({
        message: (x as Error)?.message ?? 'action failed',
        requestId: x instanceof ApiHttpError ? x.requestId : undefined,
      })
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

  // Nothing is actionable: say which gate closed, once, rather than showing three
  // disabled buttons with the same explanation under each.
  const anyEnabled =
    gates.ACCEPT_RECOMMENDATION.enabled ||
    gates.OVERRIDE_RECOMMENDATION.enabled ||
    gates.REQUEST_INFORMATION.enabled

  return (
    <div className="panel space-y-3 p-5">
      <div className="text-sm font-semibold text-white">Your decision</div>

      {!anyEnabled && (
        <p className="text-sm text-[#c4b5fd]">{gates.ACCEPT_RECOMMENDATION.blockedReason}</p>
      )}

      <textarea
        className="field"
        rows={3}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        disabled={!anyEnabled}
        placeholder="Comment. Required for an override, and for a request for information."
      />

      {gates.OVERRIDE_RECOMMENDATION.enabled && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="label mb-0">Override outcome:</span>
          {(['APPROVED', 'DENIED'] as const).map((o) => (
            <button
              key={o}
              type="button"
              aria-pressed={overrideOut === o}
              onClick={() => setOverrideOut(o)}
              className={`chip ${overrideOut === o ? (o === 'APPROVED' ? 'chip-success' : 'chip-danger') : 'chip-neutral'}`}
            >
              {o === 'APPROVED' ? 'Approve instead' : 'Deny instead'}
            </button>
          ))}
        </div>
      )}

      {err && (
        <div className="text-sm text-[#fca5a5]">
          <p>{err.message}</p>
          {err.requestId && (
            <p className="mono mt-1 text-xs text-[#8fa8c4]">request {err.requestId}</p>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <ActionButton
          gate={gates.ACCEPT_RECOMMENDATION}
          busy={busy}
          className="btn-success"
          icon={<Check size={15} />}
          label="Accept the AI recommendation"
          onClick={() => run(() => session.client.accept(id, text || undefined, qualification))}
        />
        <ActionButton
          gate={gates.REQUEST_INFORMATION}
          busy={busy}
          className="btn-amber"
          icon={<ClipboardList size={15} />}
          label="Return for information"
          // `requested_information` is min_length=1 server-side. The previous UI
          // substituted "Additional information is required." when the box was empty,
          // which writes a sentence the reviewer never typed into an append-only audit
          // record. Refuse instead of inventing their words.
          disabledReason={text ? null : 'State what the submitter must supply.'}
          onClick={() => run(() => session.client.requestInfo(id, text, qualification))}
        />
        <ActionButton
          gate={gates.OVERRIDE_RECOMMENDATION}
          busy={busy}
          className="btn-danger"
          icon={<X size={15} />}
          label="Record override"
          disabledReason={text ? null : 'A rationale is required for an override.'}
          onClick={() => run(() => session.client.override(id, overrideOut, text, qualification))}
        />
      </div>

      <ul className="space-y-1">
        {(Object.keys(gates) as AvailableAction[]).map((action) =>
          gates[action].blockedReason && anyEnabled ? (
            <li key={action} className="text-xs text-[#8fa8c4]">
              <span className="mono">{action}</span>: {gates[action].blockedReason}
            </li>
          ) : null,
        )}
      </ul>
    </div>
  )
}

/**
 * One action control. Disabled unless the server permits it by state AND by authority;
 * the reason is shown rather than left for the reviewer to discover by clicking.
 */
function ActionButton({
  gate,
  busy,
  className,
  icon,
  label,
  onClick,
  disabledReason,
}: {
  gate: { enabled: boolean; blockedReason: string | null }
  busy: boolean
  className: string
  icon: React.ReactNode
  label: string
  onClick: () => void
  disabledReason?: string | null
}) {
  const blocked = gate.blockedReason ?? disabledReason ?? null
  const disabled = busy || !gate.enabled || Boolean(disabledReason)
  return (
    <button
      type="button"
      className={`btn ${className}`}
      disabled={disabled}
      title={blocked ?? undefined}
      onClick={onClick}
    >
      {icon} {label}
    </button>
  )
}
