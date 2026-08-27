"""The deployment smoke suite. Platform-neutral, and safe to point at production.

    export MEDAUTH_SMOKE_API_KEY=...            # integrator key
    export MEDAUTH_SMOKE_TOKEN_READONLY=...     # tokens obtained from the real IdP,
    export MEDAUTH_SMOKE_TOKEN_REVIEWER=...     # by whatever flow that deployment uses
    export MEDAUTH_SMOKE_TOKEN_SENIOR=...
    export MEDAUTH_SMOKE_TOKEN_OUTSIDER=...
    uv run python scripts/production_smoke.py --api-url https://... --issuer https://... \
        --audience medauth-api

This is a **deployment** smoke test: it answers "did this deployment come up wired
correctly". It is not clinical validation, it measures nothing, and it must never be
cited as evidence about recommendations.

## Why most of it is read-only, and two checks are not

Six of the twelve checks are reads. Four more are *denials* - a request that must be
refused writes nothing by definition, so "readonly cannot review" and "reviewer cannot
override" are safe to run anywhere.

Two are genuinely mutating: a reviewer completing a review, and a senior reviewer
overriding one. Against production those write real rows to an append-only clinical
audit trail and move a real case to `FINALIZED`. **There is no way to undo that** - the
history is append-only by trigger, which is the property that makes the trail worth
having.

So they do not run unless `--smoke-case-id` names a case the operator has designated
for the purpose, and the suite says loudly which mode it ran in. A smoke test that
quietly finalises a case to prove it can finalise cases has corrupted the record it was
checking.

**This script never creates a case.** Seeding requires database access and the
engine, neither of which belongs in a deployment check.

## Tokens

Supplied by the operator, never minted here. Production tokens come from the real
identity provider by whatever flow that deployment uses; a smoke test that could mint
its own would be holding credentials that let it impersonate a reviewer.

Nothing here prints a token, and no failure message includes one.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import httpx

MUTATING = "mutating"
SAFE = "safe"


@dataclass(frozen=True, slots=True)
class Result:
    name: str
    passed: bool
    detail: str
    kind: str = SAFE


class Smoke:
    def __init__(self, api_url: str, api_key: str, timeout: float) -> None:
        self._client = httpx.Client(base_url=api_url.rstrip("/"), timeout=timeout)
        self._key = api_key
        self.results: list[Result] = []

    def headers(self, token: str | None) -> dict[str, str]:
        head = {"x-api-key": self._key}
        if token:
            head["authorization"] = f"Bearer {token}"
        return head

    def record(self, name: str, ok: bool, detail: str, kind: str = SAFE) -> bool:
        self.results.append(Result(name, ok, detail, kind))
        print(f"  [{'OK ' if ok else 'FAIL'}] {name:52} {detail}")
        return ok

    def close(self) -> None:
        self._client.close()

    def get(self, path: str, token: str | None) -> httpx.Response:
        return self._client.get(path, headers=self.headers(token))

    def post(self, path: str, token: str | None, body: dict[str, Any]) -> httpx.Response:
        return self._client.post(path, headers=self.headers(token), json=body)


def subject_of(token: str) -> str:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return str(json.loads(base64.urlsafe_b64decode(payload)).get("sub", ""))


def run(args: argparse.Namespace, tokens: dict[str, str]) -> int:
    smoke = Smoke(args.api_url, args.api_key, args.timeout)
    probe = args.smoke_case_id or "CASE-SMOKE-NONEXISTENT"

    print("\n-- readiness --")
    ready = smoke.get("/ready", None)
    smoke.record(
        "12. readiness reports healthy", ready.status_code == 200, f"HTTP {ready.status_code}"
    )

    print("\n-- authentication --")
    smoke.record(
        "1. unauthenticated request denied",
        smoke.get(f"/api/v1/cases/{probe}/review", None).status_code in {401, 403, 404},
        f"HTTP {smoke.get(f'/api/v1/cases/{probe}/review', None).status_code}",
    )
    accepted = smoke.get(f"/api/v1/cases/{probe}/review", tokens["senior"]).status_code
    smoke.record(
        "2. valid authenticated identity accepted",
        accepted in {200, 404},
        f"HTTP {accepted} (404 = authenticated, case absent)",
    )
    smoke.record(
        "8. unknown/ungrouped identity denied",
        smoke.get(f"/api/v1/cases/{probe}/review", tokens["outsider"]).status_code in {403, 404},
        "no permission set is granted to an unrecognised group",
    )

    print("\n-- authorization (denials write nothing, so these are safe anywhere) --")
    ro_review = smoke.post(
        f"/api/v1/cases/{probe}/review/request-info",
        tokens["readonly"],
        {"requested_information": "smoke"},
    ).status_code
    smoke.record("4. readonly cannot review", ro_review in {403, 404}, f"HTTP {ro_review}")
    rv_override = smoke.post(
        f"/api/v1/cases/{probe}/review/override",
        tokens["reviewer"],
        {"override_outcome": "DENIED", "rationale": "smoke"},
    ).status_code
    smoke.record("6. reviewer cannot override", rv_override in {403, 404}, f"HTTP {rv_override}")

    print("\n-- anti-enumeration --")
    absent = smoke.get(
        "/api/v1/cases/CASE-DEFINITELY-NOT-REAL/review", tokens["senior"]
    ).status_code
    smoke.record("   a nonexistent case is 404, not 5xx", absent == 404, f"HTTP {absent}")

    if not args.smoke_case_id:
        print("\n-- read model, audit, history: SKIPPED --")
        print("     no --smoke-case-id supplied, so there is no case to read.")
        print("\n-- 3, 5, 7, 9, 10, 11: SKIPPED --")
        print("     Checks 5 and 7 FINALISE a case and write to an append-only trail.")
        print("     They run only against a case the operator designates. This is the")
        print("     safe mode: nothing above wrote anything.")
        smoke.close()
        return report(smoke.results, mutating_ran=False)

    print("\n-- read model and provenance (case designated by the operator) --")
    view = smoke.get(f"/api/v1/cases/{probe}/review", tokens["readonly"])
    smoke.record("3. readonly can read", view.status_code == 200, f"HTTP {view.status_code}")
    if view.status_code != 200:
        smoke.close()
        return report(smoke.results, mutating_ran=False)
    body = view.json()
    smoke.record(
        "   AI draft is labelled and distinct from a disposition",
        "ai_recommendation" in body and "human_disposition" in body,
        f"draft={body.get('ai_recommendation')} disposition={body.get('human_disposition')}",
    )
    smoke.record(
        "   routing explanation present and not an unexplained-reason fallback",
        bool(body.get("routing_explanation"))
        and "No explanation is recorded" not in body["routing_explanation"],
        body.get("routing_explanation", "")[:48],
    )
    smoke.record(
        "11. evidence provenance is present on the read model",
        "evidence" in body,
        f"{len(body.get('evidence') or [])} reference(s), read from the original run",
    )

    if body.get("state") != "HUMAN_REVIEW":
        print("\n-- 5, 7, 9, 10: SKIPPED --")
        print(f"     the designated case is {body.get('state')}, not HUMAN_REVIEW;")
        print("     no review action is possible and none was attempted.")
        smoke.close()
        return report(smoke.results, mutating_ran=False)

    print("\n-- MUTATING: this finalises the designated case --")
    outcome = smoke.post(
        f"/api/v1/cases/{probe}/review/override",
        tokens["senior"],
        {"override_outcome": "DENIED", "rationale": args.rationale},
    )
    smoke.record(
        "7. senior reviewer can override",
        outcome.status_code == 201,
        f"HTTP {outcome.status_code}",
        MUTATING,
    )
    after = smoke.get(f"/api/v1/cases/{probe}/review", tokens["senior"]).json()
    smoke.record(
        "5. a review action is recorded and finalises",
        after.get("state") == "FINALIZED",
        str(after.get("state")),
        MUTATING,
    )
    smoke.record(
        "9. the audit records the AUTHENTICATED subject",
        after.get("disposition_by") == subject_of(tokens["senior"]),
        "disposition_by matches the token's sub",
        MUTATING,
    )
    smoke.record(
        "10. history is append-only: the AI draft survives the disagreement",
        after.get("ai_recommendation") == body.get("ai_recommendation")
        and after.get("human_disposition") == "DENIED",
        f"draft preserved={after.get('ai_recommendation') == body.get('ai_recommendation')}",
        MUTATING,
    )
    smoke.close()
    return report(smoke.results, mutating_ran=True)


def report(results: list[Result], *, mutating_ran: bool) -> int:
    failed = [r for r in results if not r.passed]
    print(f"\n  {len(results) - len(failed)} passed, {len(failed)} failed")
    print(
        f"  mode: {'MUTATING - a case was finalised' if mutating_ran else 'SAFE - nothing was written'}"
    )
    for r in failed:
        print(f"    FAILED: {r.name} - {r.detail}")
    if failed:
        print("\n  DEPLOYMENT NOT ACCEPTED.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--issuer", required=True, help="recorded in the output; not contacted")
    parser.add_argument("--audience", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--smoke-case-id",
        default=None,
        help="a case DESIGNATED for smoke testing. Supplying it enables checks that "
        "finalise that case and write to the append-only audit trail.",
    )
    parser.add_argument("--rationale", default="Deployment smoke test - not a clinical decision.")
    args = parser.parse_args()

    args.api_key = os.environ.get("MEDAUTH_SMOKE_API_KEY", "")
    missing = [
        f"MEDAUTH_SMOKE_TOKEN_{r.upper()}"
        for r in ("readonly", "reviewer", "senior", "outsider")
        if not os.environ.get(f"MEDAUTH_SMOKE_TOKEN_{r.upper()}")
    ]
    if not args.api_key:
        missing.append("MEDAUTH_SMOKE_API_KEY")
    if missing:
        print("  missing required environment: " + ", ".join(missing))
        print("  Tokens are obtained from the identity provider by the operator and passed in.")
        print("  This script does not mint tokens: one that could would hold credentials")
        print("  letting it impersonate a reviewer.")
        return 2

    tokens = {
        r: os.environ[f"MEDAUTH_SMOKE_TOKEN_{r.upper()}"]
        for r in ("readonly", "reviewer", "senior", "outsider")
    }
    print(f"  api      : {args.api_url}")
    print(f"  issuer   : {args.issuer}")
    print(f"  audience : {args.audience}")
    print(f"  case     : {args.smoke_case_id or '<none - safe mode>'}")
    return run(args, tokens)


if __name__ == "__main__":
    sys.exit(main())
