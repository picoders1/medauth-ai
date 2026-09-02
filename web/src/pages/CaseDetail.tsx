import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  BrainCircuit,
  CircleAlert,
  ClipboardList,
  Clock,
  RefreshCw,
  ScrollText,
} from 'lucide-react'
import type { useSession } from '../lib/auth'
import type { AuditTrail, Case, ReviewCase } from '../lib/types'
import { StatusChip } from '../components/StatusChip'
import { ReviewTab } from './ReviewTab'
import { AuditTab, EvidenceTab, RecommendationTab } from './RecommendationTab'
import { fmt } from '../lib/format'
import { presentState } from '../lib/lifecycle'
import { ApiHttpError } from '../api/client'

type Tab = 'review' | 'recommendation' | 'evidence' | 'audit'

interface LoadError {
  message: string
  requestId?: string
}

function toLoadError(x: unknown, fallback: string): LoadError {
  return {
    message: (x as Error)?.message ?? fallback,
    requestId: x instanceof ApiHttpError ? x.requestId : undefined,
  }
}

export function CaseDetail({ session }: { session: ReturnType<typeof useSession> }) {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('review')
  const [meta, setMeta] = useState<Case | null>(null)
  const [view, setView] = useState<ReviewCase | null>(null)
  const [audit, setAudit] = useState<AuditTrail | null>(null)
  const [loading, setLoading] = useState(true)
  const [aerr, setAerr] = useState<LoadError | null>(null)
  const [notice, setNotice] = useState<LoadError | null>(null)
  const [tick, setTick] = useState(0)

  const reload = useCallback(async () => {
    setLoading(true)
    setAerr(null)
    setNotice(null)
    try {
      const m = await session.client.getCase(id)
      setMeta(m)
      try {
        setView(await session.client.getReviewView(id))
      } catch (x) {
        setNotice(toLoadError(x, 'review view unavailable'))
        setView(null)
      }
      try {
        setAudit(await session.client.getAudit(id))
      } catch {
        setAudit(null)
      }
    } catch (x) {
      setAerr(toLoadError(x, 'failed to load case'))
    } finally {
      setLoading(false)
    }
  }, [id, session.client])

  useEffect(() => {
    void reload()
  }, [reload, tick])

  if (loading) return <Centered text="Loading case…" />
  if (aerr)
    return (
      <Centered>
        <CircleAlert size={18} className="mx-auto mb-3 text-[#fca5a5]" />
        <p className="text-[#fca5a5]">{aerr.message}</p>
        {aerr.requestId && <p className="mono mt-1 text-xs">request {aerr.requestId}</p>}
        <button className="btn btn-ghost mt-4" onClick={() => setTick((t) => t + 1)}>
          Retry
        </button>
      </Centered>
    )

  const state = meta ? presentState(meta.state) : null

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn btn-ghost !px-2.5" aria-label="Back to dashboard" onClick={() => navigate('/')}>
          <ArrowLeft size={16} />
        </button>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="mono text-lg font-semibold tracking-tight text-white">{id}</h1>
            {meta && <StatusChip state={meta.state} />}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-[#8fa8c4]">
            <span className="mono">
              {meta?.procedure_code} ({meta?.code_system})
            </span>
            <span className="mono">· {meta?.date_of_service}</span>
            {meta?.jurisdiction && <span className="mono">· {meta.jurisdiction}</span>}
            <span>· {meta?.created_at ? fmt(meta.created_at) : ''}</span>
          </div>
        </div>
        <button
          className="btn btn-ghost ml-auto"
          onClick={() => setTick((t) => t + 1)}
          title="Re-read this case from the API"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {/*
        What the state MEANS, on the case itself. `POST /cases` accepts a case and does
        not execute the pipeline, so a case sits in RECEIVED with no recommendation by
        design; without this sentence that reads as a broken console rather than as the
        architecture doing what it says.
      */}
      {state && (
        <div className="panel px-4 py-3 text-sm text-[#c7d2e8]">
          <span className="font-medium text-white">{state.label}.</span> {state.meaning}
        </div>
      )}

      {notice && (
        <div className="panel border-[#7c3aed]/40 px-4 py-2.5 text-sm text-[#c4b5fd]">
          <div className="flex items-center gap-2">
            <CircleAlert size={15} /> {notice.message}
          </div>
          {notice.requestId && (
            <p className="mono mt-1 text-xs text-[#8fa8c4]">request {notice.requestId}</p>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-1 border-b border-[#1c2742]" role="tablist">
        <TabBtn active={tab === 'review'} onClick={() => setTab('review')} icon={<ClipboardList size={14} />}>
          Review
        </TabBtn>
        <TabBtn
          active={tab === 'recommendation'}
          onClick={() => setTab('recommendation')}
          icon={<BrainCircuit size={14} />}
        >
          Recommendation
        </TabBtn>
        <TabBtn active={tab === 'evidence'} onClick={() => setTab('evidence')} icon={<ScrollText size={14} />}>
          Evidence &amp; rationale
        </TabBtn>
        <TabBtn active={tab === 'audit'} onClick={() => setTab('audit')} icon={<Clock size={14} />}>
          Audit trail
        </TabBtn>
      </div>

      {tab === 'review' && (
        <ReviewTab session={session} id={id} view={view} onChanged={() => setTick((t) => t + 1)} />
      )}
      {tab === 'recommendation' && <RecommendationTab view={view} />}
      {tab === 'evidence' && <EvidenceTab view={view} />}
      {tab === 'audit' && <AuditTab audit={audit} />}

      {/*
        Provenance. The input digest proves which submission produced which
        recommendation without the clinical note living anywhere, and the audit count
        says how much record exists behind this page. Both are already in the API
        response; the previous build fetched them and showed neither.
      */}
      {(meta || view) && (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-[#1c2742] pt-4 text-xs text-[#8fa8c4]">
          {view && <span>{view.audit_event_count} audit events recorded</span>}
          {(meta?.input_sha256 ?? view?.input_sha256) && (
            <span>
              · input digest{' '}
              <span className="mono text-[#c7d2e8]">
                {(meta?.input_sha256 ?? view?.input_sha256 ?? '').slice(0, 16)}…
              </span>
            </span>
          )}
          {view?.request_id && (
            <span>
              · request <span className="mono text-[#c7d2e8]">{view.request_id}</span>
            </span>
          )}
        </p>
      )}
    </div>
  )
}

function TabBtn({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium transition ${
        active ? 'border-[#3b82f6] text-white' : 'border-transparent text-[#8fa8c4] hover:text-white'
      }`}
    >
      {icon} {children}
    </button>
  )
}

function Centered({ text, children }: { text?: string; children?: React.ReactNode }) {
  return (
    <div className="px-1 py-24 text-center text-sm text-[#8fa8c4]">
      {text}
      {children}
    </div>
  )
}
