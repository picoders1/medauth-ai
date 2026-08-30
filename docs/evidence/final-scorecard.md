# Final evidence scorecard

Every row cites something in this repository. Nothing is asserted without it.

| Area | Status | Evidence |
|---|---|---|
| Core application | **COMPLETE** | 102 modules, 6 migrations (head `0006_reviewer_identity`), 62 test modules |
| HITL | **COMPLETE** | accept / request-info / override verified through the published port; draft and disposition separate; override preserves the draft |
| Authentication | **COMPLETE** | RS256 via JWKS; issuer, audience, expiry, nbf, subject, algorithm enforced; rotation verified; 19 negative cases, one identical `401` |
| Authorization | **COMPLETE** | service-layer matrix through HTTPS; unknown group grants nothing; type checked before permissions |
| Audit / provenance | **COMPLETE** | provider `sub` + `identity_issuer`; `UPDATE`/`DELETE` refused by trigger; evidence read from the original run |
| Real IdP | **VERIFIED NON-PRODUCTION** | Keycloak 26 · `verify_idp.py` **12/12** · `verify_idp_e2e.py` **39/39** |
| Production-shaped E2E | **COMPLETE** | `verify_idp_container_e2e.py` **45/45** over HTTPS, production-mode Keycloak on persistent PostgreSQL |
| Runtime reproducibility | **COMPLETE** | clean `--no-cache` build, 37 packages, no optional-extra masking, reviewer UI renders |
| Remote CI | **PASS** | run `33310007211` on `21f94bc` (final): every step green, none skipped; Test step **952 passed, 117 skipped** |
| Mutation testing | **47/47** | where the restricted corpus is present; **37/47 with 10 named as not verified** in CI, which cannot hold it |
| Local suite | **1373 passed** | unit 648 · api 90 · security 665 · integration 79 · evaluation 516 |
| Static checks | **CLEAN** | ruff · format (428 files) · mypy (102 files) · `alembic check` · `uv lock --check` |
| Smoke suite | **7/7 safe mode** | writes zero rows, verified by row count; the two mutating checks require an operator-designated case |
| **R-86** | **BLOCKED** | 6/12 = 50% against a 0.10 ceiling · seal intact · `gold_v1` 2/2 · `gold_v2` **0/1 unspent** |
| 26-case evaluation | **NOT RUN** | `AUTHORISATION.json` records `authorised: false`; no results exist |
| Production deployment | **NOT PERFORMED** | no platform, domain, CA, secrets mechanism or operator exists |
| Enterprise SSO | **NOT DEPLOYED / NOT CLAIMED** | the verified provider is non-production |
| Clinical validation | **NOT CLAIMED** | none performed; a reviewer workflow is not one |

## Numbers deliberately absent

There is no accuracy, precision, recall or grounding figure anywhere in this repository,
because no evaluation has produced one. The methodology, the frozen datasets and the
harness all exist; the run is blocked by R-86. Inventing a figure to fill the gap is the
one thing this project refuses most consistently.
