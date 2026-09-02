import { useState } from 'react'
import { KeyRound, LogOut, ShieldCheck, UserRound } from 'lucide-react'
import type { useSession } from '../lib/auth'

export function Settings({ session }: { session: ReturnType<typeof useSession> }) {
  const [apiKey, setApiKey] = useState(session.creds.apiKey)
  const [bearer, setBearer] = useState(session.creds.bearerToken ?? '')
  const [saved, setSaved] = useState(false)

  const clear = () => {
    session.clear()
    setApiKey('')
    setBearer('')
    setSaved(false)
  }

  const save = (e: React.FormEvent) => {
    e.preventDefault()
    session.update({
      apiKey: apiKey.trim(),
      bearerToken: bearer.trim() || undefined,
    })
    setSaved(true)
    setTimeout(() => setSaved(false), 1800)
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">Connection settings</h1>
        <p className="mt-1 text-sm text-[#8a97b4]">
          Held in memory for this tab only. Nothing is written to browser storage, so a reload
          or Clear discards them and you enter them again. MEDAUTH never stores provider
          credentials.
        </p>
      </div>

      <form onSubmit={save} className="panel space-y-5 p-6">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-[#1c2a4d]">
            <KeyRound size={16} className="text-[#93c5fd]" />
          </div>
          <div className="flex-1">
            <label className="label">Caller API key (x-api-key)</label>
            <input
              className="field"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-… — identifies the integrating system"
            />
            <p className="mt-1 text-xs text-[#7a88a6]">
              Required for any request. Mint via <span className="mono">MEDAUTH_API_KEYS</span>.
            </p>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-[#0e1426]">
            <UserRound size={16} className="text-[#7a88a6]" />
          </div>
          <div className="flex-1">
            <label className="label">Reviewer bearer token (optional)</label>
            <input
              className="field"
              type="password"
              autoComplete="off"
              value={bearer}
              onChange={(e) => setBearer(e.target.value)}
              placeholder="Bearer token for human review actions"
            />
            <p className="mt-1 text-xs text-[#7a88a6]">
              Needed only for accept / override / request-info. A key never stands in for a person (OD-43).
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-[#1c2742] pt-4">
          <div className="flex items-center gap-2 text-xs text-[#7a88a6]">
            <ShieldCheck size={14} className="text-[#4ade80]" />
            in memory only, never persisted
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn btn-ghost" onClick={clear}>
              <LogOut size={15} /> Clear
            </button>
            <button type="submit" className="btn btn-primary">
              Save
            </button>
          </div>
        </div>
        {saved && <p className="text-sm text-[#4ade80]">Saved.</p>}
      </form>
    </div>
  )
}