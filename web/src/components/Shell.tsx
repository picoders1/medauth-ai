import type { ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { Settings2, ShieldCheck } from 'lucide-react'
import type { useSession } from '../lib/auth'

export function Shell({ session, children }: { session: ReturnType<typeof useSession>; children: ReactNode }) {
  const navigate = useNavigate()
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-[#1c2742] bg-[#0a0f1c]/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-5 py-3">
          <Link to="/" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 shadow-lg shadow-blue-900/40">
              <ShieldCheck size={18} style={{ color: '#fff' }} />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-semibold tracking-tight text-white">MEDAUTH</div>
              <div className="text-[11px] text-[#7a88a6]">reviewer console</div>
            </div>
          </Link>

          <nav className="ml-4 flex items-center gap-1">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `rounded-lg px-3 py-1.5 text-sm font-medium transition ${isActive ? 'bg-white/5 text-white' : 'text-[#8a97b4] hover:text-white'}`
              }
            >
              Dashboard
            </NavLink>
            <button
              onClick={() => navigate('/cases/new')}
              className="rounded-lg px-3 py-1.5 text-sm font-medium text-[#8a97b4] hover:text-white"
            >
              New case
            </button>
          </nav>

          <div className="ml-auto flex items-center gap-3">
            {session.configured ? (
              <span className="chip chip-success">connected</span>
            ) : (
              <span className="chip chip-amber">not configured</span>
            )}
            <NavLink
              to="/settings"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-[#8a97b4] transition hover:bg-white/5 hover:text-white"
            >
              <Settings2 size={16} />
            </NavLink>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-5 py-6">{children}</main>
    </div>
  )
}