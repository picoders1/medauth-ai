import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Send } from 'lucide-react'
import type { useSession } from '../lib/auth'
import type { SubmitCasePayload } from '../lib/types'

export function NewCase({ session }: { session: ReturnType<typeof useSession> }) {
  const navigate = useNavigate()
  const [form, setForm] = useState({
    caseId: '',
    clinicalNote: '',
    procedureCode: '',
    codeSystem: 'CPT',
    dateOfService: new Date().toISOString().slice(0, 10),
    diagnosisCodes: '',
    jurisdiction: '',
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }))

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr(null)
    if (!form.procedureCode.trim()) {
      setErr('procedure code is required')
      return
    }
    const payload: SubmitCasePayload = {
      procedure_code: form.procedureCode.trim(),
      code_system: form.codeSystem.trim() || 'CPT',
      date_of_service: form.dateOfService,
      clinical_note: form.clinicalNote.trim() || 'synthetic note for adjudication',
      diagnosis_codes: form.diagnosisCodes.split(',').map((d) => d.trim()).filter(Boolean),
      jurisdiction: form.jurisdiction.trim() || undefined,
    }
    if (form.caseId.trim()) payload.case_id = form.caseId.trim()

    setBusy(true)
    try {
      const res = await session.client.submitCase(payload)
      navigate(`/cases/${encodeURIComponent(res.case_id)}`)
    } catch (x) {
      setErr((x as Error)?.message ?? 'request failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate('/')} className="btn btn-ghost !px-2.5">
          <ArrowLeft size={16} />
        </button>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Submit a case</h1>
          <p className="mt-1 text-sm text-[#8a97b4]">Deterministic adjudication, synthetic data only.</p>
        </div>
      </div>

      <form onSubmit={submit} className="panel space-y-5 p-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Case id (optional)</label>
            <input className="field" value={form.caseId} onChange={(e) => set('caseId', e.target.value)} placeholder="CASE-XXXX" />
          </div>
          <div>
            <label className="label">Date of service</label>
            <input type="date" className="field" value={form.dateOfService} onChange={(e) => set('dateOfService', e.target.value)} />
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label className="label">Procedure code</label>
            <input className="field" value={form.procedureCode} onChange={(e) => set('procedureCode', e.target.value)} placeholder="R0070" />
          </div>
          <div>
            <label className="label">Code system</label>
            <input className="field" value={form.codeSystem} onChange={(e) => set('codeSystem', e.target.value)} placeholder="CPT" />
          </div>
          <div>
            <label className="label">Jurisdiction</label>
            <input className="field" value={form.jurisdiction} onChange={(e) => set('jurisdiction', e.target.value)} placeholder="XX (optional)" />
          </div>
        </div>

        <div>
          <label className="label">Diagnosis codes (comma separated)</label>
          <input className="field" value={form.diagnosisCodes} onChange={(e) => set('diagnosisCodes', e.target.value)} placeholder="G82.35, M54.5" />
        </div>

        <div>
          <label className="label">Clinical note (synthetic only)</label>
          <textarea
            className="field min-h-[120px] resize-y"
            value={form.clinicalNote}
            onChange={(e) => set('clinicalNote', e.target.value)}
            placeholder="No real PHI — synthetic data. Leave empty for a deterministic fixture note."
          />
          <p className="mt-1 text-xs text-[#7a88a6]">Hashed on receipt; clinical text is never persisted as plaintext.</p>
        </div>

        <div className="flex items-center justify-end border-t border-[#1c2742] pt-4">
          {err && <p className="mr-auto text-sm text-[#fca5a5]">{err}</p>}
          <button type="submit" className="btn btn-primary" disabled={busy}>
            <Send size={15} /> {busy ? 'Submitting…' : 'Submit case'}
          </button>
        </div>
      </form>
    </div>
  )
}