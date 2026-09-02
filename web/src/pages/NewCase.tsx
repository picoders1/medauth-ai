import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Info, Send } from 'lucide-react'
import type { useSession } from '../lib/auth'
import type { SubmitCasePayload } from '../lib/types'
import { ApiHttpError } from '../api/client'

/**
 * Submit one case.
 *
 * ## `case_id` is required, and the caller owns it
 *
 * `SubmitCaseRequest.case_id` has no default (`app/api/v1/schemas.py`), and
 * `docs/architecture/application-lifecycle.md` §4 says why: "case ids are the caller's;
 * silently returning the existing case would hide a collision between two different
 * requests". A duplicate submission is REJECTED rather than deduplicated. The server
 * therefore must not mint an id, and this form previously labelled the field "optional"
 * and omitted it when blank — which produced a 422 on the documented happy path.
 *
 * ## Submitting does not run the case
 *
 * `POST /cases` accepts and persists; it does not execute the pipeline. That separation
 * is deliberate — binding a multi-second run to the HTTP request would make intake
 * availability depend on a provider defect that is explicitly not ours — so the form
 * says so rather than leaving the reviewer to infer a fault from an empty recommendation.
 */
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
  const [err, setErr] = useState<{ message: string; requestId?: string } | null>(null)
  const [touched, setTouched] = useState(false)

  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }))

  const missingCaseId = form.caseId.trim().length === 0
  const missingProcedure = form.procedureCode.trim().length === 0
  // `clinical_note` is min_length=1 server-side, so an empty note is a 422 rather than
  // a defaulted fixture. Refusing here says which field, instead of relaying a 422.
  const missingNote = form.clinicalNote.trim().length === 0

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setTouched(true)
    setErr(null)
    if (missingCaseId || missingProcedure || missingNote) return

    const payload: SubmitCasePayload = {
      case_id: form.caseId.trim(),
      procedure_code: form.procedureCode.trim(),
      code_system: form.codeSystem.trim() || 'CPT',
      date_of_service: form.dateOfService,
      clinical_note: form.clinicalNote.trim(),
      diagnosis_codes: form.diagnosisCodes
        .split(',')
        .map((d) => d.trim())
        .filter(Boolean),
    }
    // Absent jurisdiction means jurisdictional policies do NOT apply — never that they
    // do. Send the field only when the submitter stated one.
    const jurisdiction = form.jurisdiction.trim()
    if (jurisdiction) payload.jurisdiction = jurisdiction

    setBusy(true)
    try {
      const res = await session.client.submitCase(payload)
      navigate(`/cases/${encodeURIComponent(res.case_id)}`)
    } catch (x) {
      setErr({
        message: (x as Error)?.message ?? 'request failed',
        requestId: x instanceof ApiHttpError ? x.requestId : undefined,
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate('/')} className="btn btn-ghost !px-2.5" aria-label="Back to dashboard">
          <ArrowLeft size={16} />
        </button>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Submit a case</h1>
          <p className="mt-1 text-sm text-[#8a97b4]">Synthetic data only.</p>
        </div>
      </div>

      <div className="panel flex gap-2.5 px-4 py-3 text-sm text-[#c7d2e8]">
        <Info size={15} className="mt-0.5 shrink-0 text-[#93c5fd]" />
        <p>
          Submitting records the case and <strong>does not run it</strong>. The case will be{' '}
          <span className="mono">RECEIVED</span> with no recommendation until a run is started —
          intake and execution are separate steps in this system.
        </p>
      </div>

      <form onSubmit={submit} noValidate className="panel space-y-5 p-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="case-id">
              Case id (required)
            </label>
            <input
              id="case-id"
              className={`field ${touched && missingCaseId ? 'field-danger' : ''}`}
              value={form.caseId}
              onChange={(e) => set('caseId', e.target.value)}
              placeholder="CASE-XXXX"
              aria-invalid={touched && missingCaseId}
            />
            <p className="mt-1 text-xs text-[#7a88a6]">
              Yours to choose, and yours to keep unique — a duplicate id is refused, never merged.
            </p>
          </div>
          <div>
            <label className="label" htmlFor="dos">
              Date of service
            </label>
            <input
              id="dos"
              type="date"
              className="field"
              value={form.dateOfService}
              onChange={(e) => set('dateOfService', e.target.value)}
            />
            <p className="mt-1 text-xs text-[#7a88a6]">
              Selects the policy version. Never &ldquo;latest&rdquo;.
            </p>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label className="label" htmlFor="proc">
              Procedure code (required)
            </label>
            <input
              id="proc"
              className={`field ${touched && missingProcedure ? 'field-danger' : ''}`}
              value={form.procedureCode}
              onChange={(e) => set('procedureCode', e.target.value)}
              placeholder="R0070"
              aria-invalid={touched && missingProcedure}
            />
          </div>
          <div>
            <label className="label" htmlFor="codesys">
              Code system
            </label>
            <input
              id="codesys"
              className="field"
              value={form.codeSystem}
              onChange={(e) => set('codeSystem', e.target.value)}
              placeholder="CPT"
            />
          </div>
          <div>
            <label className="label" htmlFor="juris">
              Jurisdiction
            </label>
            <input
              id="juris"
              className="field"
              value={form.jurisdiction}
              onChange={(e) => set('jurisdiction', e.target.value)}
              placeholder="optional"
            />
          </div>
        </div>

        <div>
          <label className="label" htmlFor="dx">
            Diagnosis codes (comma separated)
          </label>
          <input
            id="dx"
            className="field"
            value={form.diagnosisCodes}
            onChange={(e) => set('diagnosisCodes', e.target.value)}
            placeholder="G82.35, M54.5"
          />
        </div>

        <div>
          <label className="label" htmlFor="note">
            Clinical note — synthetic only (required)
          </label>
          <textarea
            id="note"
            className={`field min-h-[120px] resize-y ${touched && missingNote ? 'field-danger' : ''}`}
            value={form.clinicalNote}
            onChange={(e) => set('clinicalNote', e.target.value)}
            placeholder="No real PHI. Synthetic data only."
            aria-invalid={touched && missingNote}
          />
          <p className="mt-1 text-xs text-[#7a88a6]">
            Hashed on receipt; the note itself is never persisted.
          </p>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-3 border-t border-[#1c2742] pt-4">
          {touched && (missingCaseId || missingProcedure || missingNote) && (
            <p className="mr-auto text-sm text-[#fca5a5]">
              {[
                missingCaseId && 'case id',
                missingProcedure && 'procedure code',
                missingNote && 'clinical note',
              ]
                .filter(Boolean)
                .join(', ')}{' '}
              required
            </p>
          )}
          {err && (
            <div className="mr-auto text-sm text-[#fca5a5]">
              <p>{err.message}</p>
              {err.requestId && (
                <p className="mono mt-1 text-xs text-[#8fa8c4]">request {err.requestId}</p>
              )}
            </div>
          )}
          <button type="submit" className="btn btn-primary" disabled={busy}>
            <Send size={15} /> {busy ? 'Submitting…' : 'Submit case'}
          </button>
        </div>
      </form>
    </div>
  )
}
