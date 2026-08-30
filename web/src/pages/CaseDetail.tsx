import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  BrainCircuit,
  CircleAlert,
  ClipboardList,
  Clock,
  History,
  ScrollText,
} from 'lucide-react'
import type { useSession } from '../lib/auth'
import type { AuditTrail, Case, ReviewCase } from '../lib/types'
import { StatusChip } from '../components/StatusChip'
import { ReviewTab } from './ReviewTab'
import { AuditTab, EvidenceTab, RecommendationTab } from './RecommendationTab'
import { fmt } from '../lib/format'

type Tab = 'review' | 'recommendation' | 'evidence' | 'audit'

export function CaseDetail({ session }: { session: ReturnType<typeof useSession> }) {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('review')
  const [meta, setMeta] = useState<Case | null>(null)
  const [view, setView] = useState<ReviewCase | null>(null)
  const [audit, setAudit] = useState<AuditTrail | null>(null)
  const [loading, setLoading] = useState(true)
  const [aerr, setAerr] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
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
        setNotice((x as Error)?.message ?? 'review view unavailable')
        setView(null)
      }
      try {
        setAudit(await session.client.getAudit(id))
      } catch {
        setAudit(null)
      }
    } catch (x) {
      setAerr((x as Error)?.message ?? 'failed to load case')
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
      <Centered text="">
        <CircleAlert size={18} className="mx-auto mb-3 text-[#fca5a5]" />
        <p className="text-[#fca5a5]">{aerr}</p>
        <button className="btn btn-ghost mt-4" onClick={() => setTick((t) => t + 1)}>
          Retry
        </button>
      </Centered>
    )

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn btn-ghost !px-2.5" onClick={() => navigate('/')}>
          <ArrowLeft size={16} />
        </button>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="mono text-lg font-semibold tracking-tight text-white">{id}</h1>
            {meta && <StatusChip state={meta.state} />}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-[#8fa8c4]">
            <span className="mono">{meta?.procedure_code} ({meta?.code_system})</span>
            <span className="mono">· {meta?.date_of_service}</span>
            {meta?.jurisdiction && <span className="mono">· {meta.jurisdiction}</span>}
            <span>· {meta?.created_at ? fmt(meta.created_at) : ''}</span>
          </div>
        </div>
      </div>

      {notice && (
        <div className="panel flex items-center gap-2 border-[#7c3aed]/40 px-4 py-2.5 text-sm text-[#c4b5fd]">
          <CircleAlert size={15} /> {notice}
        </div>
      )}

      <div className="flex flex-wrap gap-1 border-b border-[#1c2742]">
        <TabBtn active={tab === 'review'} onClick={() => setTab('review')} icon={<ClipboardList size={14} />}>
          Review
        </TabBtn>
        <TabBtn active={tab === 'recommendation'} onClick={() => setTab('recommendation')} icon={<BrainCircuit size={14} />}>
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
      {void History}
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
  return <div className="px-1 py-24 text-center text-sm text-[#8fa8c4]">{text}{children}</div>
}