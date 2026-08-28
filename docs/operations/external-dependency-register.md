# External dependency register

**A control document, not a wish list.** Every row is something MEDAUTH cannot resolve
from its own repository, with the exact decision required and the evidence that would
close it.

**No owner is named.** Owner categories describe the *kind* of role that must decide;
this repository has no standing to name a person or an organisation, and inventing one
would make an unmade decision look made.

**Nothing here is an application defect.** The application has no open blocker.

---

| Dependency | Classification | Current state | Why blocked | Required decision / action | Evidence required to close | Owner category |
|---|---|---|---|---|---|---|
| **R-86 provider** | **EXTERNAL BLOCKER** | `6/12 = 50%` against a `≤10%` ceiling; gate `BLOCKED` | The failure is inside a decoder MEDAUTH does not operate and cannot inspect: no administrative surface, no runtime version reported, no local alternative. Every remaining discriminator is provider-internal | Obtain decoder evidence, establish root cause, apply a provider-side correction, verify independently | A revalidation of the **unchanged** sealed reproducer returning `PASS` at ≤ 0.10 | **UPSTREAM PROVIDER / MODEL PLATFORM OWNER** |
| **Production platform** | EXTERNAL DECISION REQUIRED | Not selected. No IaC, Helm, Kustomize, systemd or managed-platform config exists anywhere | Choosing one is a deployment decision with operational and licensing consequences this repository has no basis to make | Select the deployment target | A target named, with the seven provider-neutral requirements in the go-live contract satisfied | INFRASTRUCTURE / PLATFORM OWNER |
| **Production IdP** | EXTERNAL DECISION REQUIRED | Keycloak 26 verified **non-production** only; no production instance, issuer, realm or owner recorded | Ownership and operation of an identity provider is an organisational commitment, not a configuration value | Decide provider, instance, issuer, realm/tenant, persistence, TLS and who operates it | `scripts/verify_idp.py` passing against the production issuer, with a real token | IDENTITY / PLATFORM OWNER |
| **Production secrets** | EXTERNAL DECISION REQUIRED | `.env` files on one machine. The application supports environment **and** file injection (`MEDAUTH_SECRETS_DIR`) | The interface exists; the mechanism is a platform choice | Select the mechanism, define injection, rotation ownership and recovery | Secrets delivered by the approved mechanism, absent from image and environment, with a rotation procedure recorded | SECURITY / PLATFORM OWNER |
| **DNS / CA** | EXTERNAL DECISION REQUIRED | Local `*.localhost` names and a throwaway local CA | No domain is owned and no certificate authority is established | Establish the production domain, DNS ownership, certificate authority and renewal ownership | A certificate chaining to a real CA, serving the canonical issuer and API hostnames | INFRASTRUCTURE |
| **Backup / restore / DR** | EXTERNAL OPERATIONS | Not performed. No backup, no verification, no restore has ever run | Backups without a tested restore are a belief, not a control | Define and execute application-DB and Keycloak-DB backup, verification and restore; set RPO and RTO | A **completed restore drill**, plus RPO/RTO recorded as decisions | OPERATIONS |
| **HA / monitoring / alerting** | EXTERNAL OPERATIONS | No HA topology. Logging and `/metrics` exist; **alerting does not** | Thresholds and availability targets are business decisions | Define topology, health monitoring, alert routing and SLO/SLA | Alerts firing against defined thresholds in the deployed environment | PLATFORM / OPERATIONS |
| **MFA** | ORGANIZATIONAL DECISION REQUIRED | **Technically available, deliberately not configured** | Requiring MFA is a policy decision. Configuring it on a fixture realm would let "MFA is configured" be recorded when the true statement is "MFA is available" | Decide whether MFA is required, for whom, and with which factors | The policy recorded and enforced at the production provider | ORGANISATIONAL / SECURITY POLICY OWNER |
| **Identity lifecycle** | ORGANIZATIONAL DECISION REQUIRED | Four fixture identities. No joiner/mover/leaver process | Account lifecycle is directory governance; MEDAUTH consumes group membership and must not encode it | Define joiner/mover/leaver, disablement timeliness, ownership and periodic review | A documented process with an accountable owner | IDENTITY GOVERNANCE OWNER |
| **Senior-reviewer governance** | ORGANIZATIONAL DECISION REQUIRED | No owner. `medauth-senior-reviewer` confers the authority to **overturn a recommendation** | Without an owner, that authority is granted by whoever administers the directory | Define approval authority, membership criteria, periodic access review and emergency access | Membership decisions traceable to a named approving authority | CLINICAL / OPERATIONAL GOVERNANCE OWNER |
| **Access-token lifetime** | ORGANIZATIONAL DECISION REQUIRED | 900s in the non-production realm | **MEDAUTH does not check revocation — measured.** A disabled account's unexpired token still authenticates, so this value *is* the entire revocation exposure window | Set the production lifetime deliberately, and decide whether introspection is required | The value recorded as a decision with its rationale | SECURITY POLICY OWNER |
| **Audit retention** | ORGANIZATIONAL DECISION REQUIRED | Retention is implemented and deletes by `created_at` only; **no period is set** | A retention period for clinical decision records has regulatory dimensions this repository must not assume | Set the retention period, archival and any deletion policy | The period recorded, with the regulatory basis stated by its owner | COMPLIANCE / RECORDS OWNER |
| **Enterprise SSO approval** | ORGANIZATIONAL DECISION REQUIRED | Not sought, not granted | No organisation has been identified | Obtain approval to integrate with the enterprise identity estate | A recorded approval from the accountable authority | ORGANISATIONAL AUTHORITY |

## Two gaps that no row above closes

Recorded here because they will otherwise be read as covered by "production hardening",
and they are not:

- **Token revocation is not checked.** Measured: with an account disabled in the realm, a
  *new* login is refused while the *existing* token still authenticates. Only
  `accessTokenLifespan` bounds it.
- **Subject reassignment cannot be detected.** An operator who mints a new user carrying a
  retired `sub` produces a valid token resolving to the wrong person's history. This is a
  property of the directory, not of MEDAUTH, and it is not mitigated.
