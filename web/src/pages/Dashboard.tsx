import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ClipboardList, FilePlus2, FileSearch, KeyRound, Search } from 'lucide-react'
import type { useSession } from '../lib/auth'

export function Dashboard({ session }: { session: ReturnType<typeof useSession> }) {
  const [q, setQ] = useState('')
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  if (!session.configured) {
    return (
      <div className="mx-auto mt-24 max-w-md text-center">
        <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-[#1c2742] bg-[#0e1426]">
          <FileSearch size={26} style={{ color: '#7a88a6' }} />
        </div>
        <h1 className="text-xl font-semibold text-white">Connect to begin</h1>
        <p className="mt-2 text-sm text-[#8a97b4]">
          Add a caller API key (and optionally a reviewer bearer token) in Settings to look up and
          review cases.
        </p>
        <Link to="/settings" className="btn btn-primary mt-6">
          Open settings
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">Case queue</h1>
        <p className="mt-1 text-sm text-[#8a97b4]">
          MEDAUTH has no enumeration endpoint by design — open a case by its ID.
        </p>
      </div>

      <form
        className="panel flex items-center gap-3 p-3"
        onSubmit={(e) => {
          e.preventDefault()
          const id = q.trim()
          if (!id) {
            setError('enter a case id')
            return
          }
          setError(null)
          navigate(`/cases/${encodeURIComponent(id)}`)
        }}
      >
        <Search size={18} style={{ color: '#5b6b8a' }} />
        <input
          className="field flex-1 border-transparent bg-transparent"
          placeholder="Case id, e.g. CASE-1007"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button type="submit" className="btn btn-primary">
          Open case
        </button>
      </form>
      {error && <p className="text-sm text-[#fca5a5]">{error}</p>}

      <div className="grid gap-3 sm:grid-cols-3">
        <Link to="/cases/new" className="panel group p-5 transition hover:border-[#3b82f6]">
          <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-[#1c2a4d] transition group-hover:bg-[#2563eb]">
            <FilePlus2 size={18} className="text-[#93c5fd]" />
          </div>
          <div className="text-sm font-semibold text-white">Submit a case</div>
          <p className="mt-1 text-xs text-[#8a97b4]">Send a single pending case for deterministic adjudication.</p>
        </Link>
        <Link to="/settings" className="panel group p-5 transition hover:border-[#3b82f6]">
          <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-[#0e1426] transition group-hover:bg-[#2563eb]">
            <KeyRound size={18} className="text-[#7a88a6] group-hover:text-white" />
          </div>
          <div className="text-sm font-semibold text-white">Connection settings</div>
          <p className="mt-1 text-xs text-[#8a97b4]">API key and optional reviewer bearer token.</p>
        </Link>
        <div className="panel p-5">
          <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-[#0e1426]">
            <ClipboardList size={18} className="text-[#7a88a6]" />
          </div>
          <div className="text-sm font-semibold text-white">Evidence &amp; audit</div>
          <p className="mt-1 text-xs text-[#8a97b4]">Available on any case detail view.</p>
        </div>
      </div>
    </div>
  )
}