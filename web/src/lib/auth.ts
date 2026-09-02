import { useMemo, useState } from 'react'
import { Client, type Credentials } from '../api/client'

/**
 * Reviewer credentials, held in memory for the life of the page.
 *
 * ## What this file used to do, and why that was a finding
 *
 * It wrote `{apiKey, bearerToken}` to `localStorage` under `medauth.credentials` and
 * read them back on load. Both values are secrets, and they are secrets of different
 * kinds:
 *
 *  - `apiKey` is the caller credential from `MEDAUTH_API_KEYS`. It is long-lived,
 *    reusable, and carries no expiry - a copy of it works until an operator revokes it.
 *  - `bearerToken` is the reviewer's identity token. It is what the audit trail
 *    attributes an accept, an override or a request-info to (OD-43). Someone holding it
 *    does not merely read cases; they leave decisions under another person's name.
 *
 * `localStorage` is readable by any script on the origin, survives a browser restart,
 * and has no expiry of its own. So the storage outlived the session for the token that
 * had no expiry anyway, and put the identity token in the one place a single injected
 * script can read in full.
 *
 * ## What holding them in memory does and does not fix
 *
 * It removes *persistence*: nothing is written, nothing survives a reload, and a shared
 * or recovered machine yields nothing. It does **not** make the credentials unreadable
 * to injected script - anything running in this page can reach React state too. The
 * claim is the narrow one: the secrets no longer outlive the tab.
 *
 * `sessionStorage` was rejected as a middle ground. It is equally script-readable, so it
 * would trade the same exposure for less inconvenience while reading, in a diff, like a
 * fix. The real upgrade is an httpOnly, SameSite session cookie set by the server, which
 * needs a session endpoint and CSRF handling the API does not have; it is written down
 * in `web/README.md` as the next step rather than half-built here.
 *
 * The cost is stated rather than hidden: a reload empties the fields and the reviewer
 * re-enters them. That is the intended behaviour of this change, not a rough edge.
 */
const LEGACY_KEY = 'medauth.credentials'

/**
 * Delete anything an earlier build of this console left behind.
 *
 * Removing the write does nothing about the secrets already sitting in the browsers of
 * everyone who ran the previous version - those persist until the user clears site data,
 * which nobody does. This is the only browser-storage call in `web/src`, it only ever
 * deletes, and `tests/unit/test_spa_contract_conformance.py` asserts that no other one
 * appears anywhere in the tree.
 */
function discardLegacyPersistedCredentials(): void {
  try {
    localStorage.removeItem(LEGACY_KEY)
  } catch {
    /* Storage can be unavailable (private mode, blocked cookies). Nothing to clean. */
  }
}

const EMPTY: Credentials = { apiKey: '', bearerToken: undefined }

export function useSession() {
  const [creds, setCreds] = useState<Credentials>(() => {
    discardLegacyPersistedCredentials()
    return EMPTY
  })

  const client = useMemo(() => new Client(creds), [creds])

  const update = (next: Credentials) => {
    setCreds(next)
  }

  const clear = () => {
    setCreds(EMPTY)
  }

  const configured = creds.apiKey.length > 0

  return { creds, client, update, clear, configured }
}
