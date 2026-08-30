import { useEffect, useMemo, useState } from 'react'
import { Client, type Credentials } from '../api/client'

const KEY = 'medauth.credentials'

export function loadCredentials(): Credentials {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<Credentials>
      if (typeof parsed.apiKey === 'string' && parsed.apiKey.length > 0) {
        return { apiKey: parsed.apiKey, bearerToken: parsed.bearerToken || '' }
      }
    }
  } catch {
    /* ignore */
  }
  return { apiKey: '', bearerToken: '' }
}

export function useSession() {
  const [creds, setCreds] = useState<Credentials>(() => loadCredentials())
  const [ready, setReady] = useState(false)

  useEffect(() => {
    setReady(true)
  }, [])

  const client = useMemo(() => new Client(creds), [creds])

  const update = (next: Credentials) => {
    localStorage.setItem(KEY, JSON.stringify(next))
    setCreds(next)
  }

  const clear = () => {
    localStorage.removeItem(KEY)
    setCreds({ apiKey: '', bearerToken: '' })
  }

  const configured = creds.apiKey.length > 0

  return { creds, client, update, clear, configured, ready }
}