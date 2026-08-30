import { Navigate, Route, Routes } from 'react-router-dom'
import { useSession } from './lib/auth'
import { Shell } from './components/Shell'
import { Dashboard } from './pages/Dashboard'
import { CaseDetail } from './pages/CaseDetail'
import { NewCase } from './pages/NewCase'
import { Settings } from './pages/Settings'

export default function App() {
  const session = useSession()

  return (
    <Shell session={session}>
      <Routes>
        <Route path="/" element={<Dashboard session={session} />} />
        <Route path="/cases/new" element={<NewCase session={session} />} />
        <Route path="/cases/:id" element={<CaseDetail session={session} />} />
        <Route path="/settings" element={<Settings session={session} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}