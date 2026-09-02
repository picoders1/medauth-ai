"""The reviewer console's TypeScript must agree with the server's Python.

## Why this test exists at all

Every defect this file guards was a **copy of a server vocabulary that drifted**. The
console declared six case states, four of which the server cannot emit; it tested
`available_actions` for `'OVERRIDE'`, a token the server has never sent; it declared an
error envelope with `code` and `title`, which the server does not use.

None of that is catchable from either side alone. A Python test sees the real enum and
not the copy; a TypeScript test sees the copy and not the real enum, so it agrees with
whatever the frontend author typed - which is exactly how the original defect survived,
and how a concurrent attempt at these tests came to assert
`available_actions: ['ACCEPT', 'OVERRIDE']` and pass. This test reads both files.

## It parses source rather than importing

`web/` has no Python-importable form and running `tsc` from pytest would make the suite
depend on a node toolchain. These read the TypeScript as text, the way
`test_layer_boundaries.py` reads Python as an AST: the guarantee wanted is "the token in
the file is the token the server sends", and that survives the file never being executed.

Marked `unit`: no database, no network, no node.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.case.lifecycle import CaseState
from app.identity.principal import Permission

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "web" / "src"

TYPES_TS = WEB / "lib" / "types.ts"
ACTIONS_TS = WEB / "lib" / "actions.ts"
LIFECYCLE_TS = WEB / "lib" / "lifecycle.ts"
REVIEW_TAB = WEB / "pages" / "ReviewTab.tsx"
RECOMMENDATION_TAB = WEB / "pages" / "RecommendationTab.tsx"


def read(path: Path) -> str:
    assert path.exists(), f"the console lost {path.relative_to(REPO)}"
    return path.read_text(encoding="utf-8")


def union_members(source: str, name: str) -> set[str]:
    """The string-literal members of `export type <name> = 'A' | 'B'`."""
    match = re.search(rf"export type {name} =\s*(.+?)\n\n", source, re.S)
    assert match, f"no `export type {name}` union found"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def server_available_actions() -> set[str]:
    """The action tokens `app/case/review_view.py` actually builds.

    Read from that module's AST rather than restated here, so this test cannot agree
    with a stale copy of the vocabulary it exists to check.
    """
    tree = ast.parse((REPO / "app" / "case" / "review_view.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Tuple):
            values = [e.value for e in node.elts if isinstance(e, ast.Constant)]
            if (
                values
                and all(isinstance(v, str) for v in values)
                and "ACCEPT_RECOMMENDATION" in values
            ):
                return set(values)
    raise AssertionError("no available-actions tuple found in app/case/review_view.py")


# --------------------------------------------------------------------------- D1


def test_the_console_declares_exactly_the_servers_case_states() -> None:
    """**Regression, defect 1.**

    The console declared `CREATED | SUBMITTED | RECOMMENDATION_READY | HUMAN_REVIEW |
    FINAL_INFO | CLOSED`. The server emits `RECEIVED | PROCESSING |
    RECOMMENDATION_READY | NEEDS_INFO | HUMAN_REVIEW | FINALIZED | FAILED`. Four
    invented, four missing, and the missing ones fell through to a neutral chip - so a
    FAILED case rendered as unremarkable.
    """
    declared = union_members(read(TYPES_TS), "CaseState")
    actual = {s.value for s in CaseState}

    assert declared == actual, (
        f"invented by the console: {sorted(declared - actual)}; "
        f"emitted by the server and unhandled: {sorted(actual - declared)}"
    )


def test_every_server_state_has_a_presentation() -> None:
    """The table in `lifecycle.ts` is total, so no state can fall through to a fallback.

    Totality is also asserted from the TypeScript side (`lifecycle.test.ts`); this is the
    half that knows what the server can actually emit.
    """
    source = read(LIFECYCLE_TS)
    table = re.search(
        r"STATE_PRESENTATION: Record<CaseState, StatePresentation> = \{(.+?)\n\}", source, re.S
    )
    assert table, "no STATE_PRESENTATION table found"
    presented = set(re.findall(r"^  ([A-Z_]+): \{", table.group(1), re.M))

    assert presented == {s.value for s in CaseState}, (
        f"missing a presentation: {sorted({s.value for s in CaseState} - presented)}"
    )


def test_a_failed_case_is_not_presented_as_neutral_or_successful() -> None:
    """Fail-closed routes toward the human, never toward a denial - and never toward a
    page that looks fine. `FAILED` must be visually distinct from a completed case."""
    source = read(LIFECYCLE_TS)
    failed = re.search(r"  FAILED: \{(.+?)\n  \}", source, re.S)
    assert failed, "FAILED has no presentation"
    assert "chip-danger" in failed.group(1)
    assert "chip-neutral" not in failed.group(1)
    assert "chip-success" not in failed.group(1)


# --------------------------------------------------------------------------- D2/D4


def test_the_console_declares_exactly_the_servers_action_tokens() -> None:
    """**Regression, defect 2.**

    `available_actions.includes('OVERRIDE')` was permanently false: the server emits
    `OVERRIDE_RECOMMENDATION`, and `Array.includes` is an exact match. Override was
    therefore unreachable in the UI for every reviewer, however senior.
    """
    declared = union_members(read(TYPES_TS), "AvailableAction")
    actual = server_available_actions()

    assert declared == actual, (
        f"console-only tokens: {sorted(declared - actual)}; "
        f"server tokens the console cannot match: {sorted(actual - declared)}"
    )


def test_no_shortened_action_token_survives_anywhere_in_the_console() -> None:
    """The specific mistake, forbidden by name.

    A shortened token does not fail loudly - it silently disables a control - so the
    absence is worth asserting directly rather than trusting the union to be consulted.
    """
    offenders: list[str] = []
    for path in sorted(WEB.rglob("*.ts*")):
        if path.name.endswith(".test.ts"):
            continue  # the mutation fixtures use the wrong tokens deliberately
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # Comments are skipped: the modules that fixed this defect describe it, and
            # a prose mention of the wrong token is the opposite of the wrong token.
            if line.lstrip().startswith(("*", "//", "/*")):
                continue
            for short in ("'ACCEPT'", "'OVERRIDE'", "'REQUEST_INFO'"):
                if short in line:
                    offenders.append(f"{path.relative_to(REPO)}:{lineno} {short}")
    assert not offenders, "a shortened action token is back: " + "; ".join(offenders)


def test_the_action_gate_reads_both_state_and_authority() -> None:
    """**Regression, defects 3 and 4.**

    Accept and request-info consulted neither gate, so they stayed clickable on a
    finalised case. Override consulted only `available_actions` while telling the
    reviewer they lacked *authority* - a permission the code had never looked at.
    """
    source = read(ACTIONS_TS)
    assert "available_actions.includes(action)" in source, "the state gate is gone"
    for flag in ("may_review", "may_override", "may_finalize"):
        assert flag in source, f"the authority gate does not read {flag}"


def test_the_permission_flags_name_real_permissions() -> None:
    """A flag named for a permission that does not exist is a client-side rule wearing
    the API's clothes."""
    source = read(ACTIONS_TS)
    labels = set(re.findall(r"may_\w+: '([A-Z_]+)'", source))
    assert labels, "no permission labels found in the gate"
    assert labels <= {p.value for p in Permission}, (
        f"not real permissions: {sorted(labels - {p.value for p in Permission})}"
    )


def test_the_gate_mirrors_the_services_per_action_permission_table() -> None:
    """The table is not uniform, and the asymmetry is the part worth pinning.

    `app/case/review.py` requires `FINALIZE_CASE` for every action **except**
    `REQUEST_INFO` - returning a case to the submitter does not dispose of it. A console
    that gated all three identically would hide an action a plain reviewer may take.
    """
    source = read(ACTIONS_TS)
    block = re.search(r"REQUIRED_PERMISSIONS[^=]+= \{(.+?)\n\}", source, re.S)
    assert block, "no REQUIRED_PERMISSIONS table found"
    table = {
        action: set(re.findall(r"'(may_\w+)'", perms))
        for action, perms in re.findall(r"  ([A-Z_]+): \[([^\]]*)\]", block.group(1))
    }

    assert table["REQUEST_INFORMATION"] == {"may_review"}
    assert table["ACCEPT_RECOMMENDATION"] == {"may_review", "may_finalize"}
    assert table["OVERRIDE_RECOMMENDATION"] == {"may_review", "may_override", "may_finalize"}


def test_the_console_never_derives_authority_from_a_qualification() -> None:
    """OD-43, restated on the client. A stated qualification grants nothing.

    `gateActions` takes only state, the action tokens and the `may_*` flags, so a
    qualification is not in its input type at all - it cannot become an authorization
    input by accident.
    """
    source = read(ACTIONS_TS)
    assert "qualification" not in source.lower(), (
        "the action gate mentions a qualification; authority must come from permissions"
    )


# --------------------------------------------------------------------------- D5


def test_the_console_treats_case_id_as_required() -> None:
    """**Regression, defect 5.**

    `SubmitCaseRequest.case_id` has no server default, and
    `docs/architecture/application-lifecycle.md` §4 makes the id the caller's: a
    duplicate is refused rather than deduplicated, so the server must not mint one. The
    form declared it optional and omitted it when blank - a 422 on the documented flow.
    """
    payload = re.search(r"export interface SubmitCasePayload \{(.+?)\n\}", read(TYPES_TS), re.S)
    assert payload, "no SubmitCasePayload found"
    assert re.search(r"^  case_id: string$", payload.group(1), re.M), (
        "case_id is optional in the console while the server requires it"
    )

    form = read(WEB / "pages" / "NewCase.tsx")
    assert "Case id (required)" in form, "the form still labels case_id optional"


# --------------------------------------------------------------------------- D6


def test_the_console_says_submitting_does_not_run_the_case() -> None:
    """**Regression, defect 6.** `POST /cases` accepts and persists; it does not execute.

    The console navigated to a detail page showing no recommendation and no actions with
    nothing saying why, so a deliberate architecture read as a broken page. The fix is
    what the UI says, and this pins that it still says it.
    """
    form = read(WEB / "pages" / "NewCase.tsx")
    assert "does not run it" in form

    lifecycle = read(LIFECYCLE_TS)
    received = re.search(r"  RECEIVED: \{(.+?)\n  \}", lifecycle, re.S)
    assert received and "Nothing has run" in received.group(1)


def test_the_console_invents_no_execution_endpoint() -> None:
    """No run/execute endpoint exists, and the console must not imply one.

    Adding a pipeline trigger to make the UI look complete would be a new feature
    smuggled in as a bug fix.
    """
    client = read(WEB / "api" / "client.ts")
    for invented in ("/run", "/execute", "/process"):
        assert invented not in client, (
            f"the console calls an endpoint that does not exist: {invented}"
        )


# --------------------------------------------------------------------------- D7


def test_the_console_renders_the_routing_reason_above_the_draft() -> None:
    """**Anti-anchoring, R-04.** The ordering the Jinja page is built around.

    A reviewer must read *why the case is here* before *what the system proposed*, or the
    interface causes the risk the register names. The Jinja equivalent of this assertion
    is `test_the_ui_never_renders_a_recommendation_as_a_decision`; the SPA's
    Recommendation tab used to be ordered the other way round.
    """
    for path in (REVIEW_TAB, RECOMMENDATION_TAB):
        source = read(path)
        reason = source.index("routing_explanation")
        draft = source.index("ai_recommendation")
        assert reason < draft, (
            f"{path.name} renders the recommendation above the reason it was routed (R-04)"
        )


def test_every_rendering_of_the_draft_is_labelled_not_a_decision() -> None:
    """The label appears every time the draft does, on every surface.

    Colour alone would not survive a monochrome print-out, and a reviewer skim-reading
    must not be able to mistake a draft for a determination.
    """
    for path in (REVIEW_TAB, RECOMMENDATION_TAB):
        source = read(path)
        drafts = source.count('tone="ai"')
        labels = len(re.findall(r"AI-generated recommendation — NOT? a decision", source, re.I))
        assert drafts > 0, f"{path.name} no longer renders the draft"
        assert labels >= drafts, f"{path.name} renders the draft without the label"


def test_the_human_disposition_is_a_separate_block_from_the_draft() -> None:
    """Two fields, never one - the property `ReviewCaseResponse` exists to preserve."""
    source = read(REVIEW_TAB)
    assert "Human disposition" in source
    assert 'tone="human"' in source
    assert "No human decision has been recorded" in source


def test_a_provider_failure_is_labelled_infrastructure_not_clinical() -> None:
    """**Regression, defect 7.**

    The console rendered the bare token under the heading "Provider note", which invites
    a reviewer to read a transport failure as a finding about the clinical facts. The
    Jinja page carries the sentence; both surfaces that show the failure now do too.
    """
    for path in (REVIEW_TAB, RECOMMENDATION_TAB):
        source = read(path)
        assert "provider_failure_kind" in source, f"{path.name} dropped the provider failure"
        assert "not a finding about the clinical facts" in source, (
            f"{path.name} renders a provider failure without saying it is infrastructure"
        )


def test_the_console_displays_the_audit_and_provenance_fields() -> None:
    """**Regression, defect 7.** Fields the console fetched and then dropped.

    `criterion_ids` connects a chunk to the criterion it was retrieved for;
    `input_sha256` proves which submission produced which recommendation;
    `audit_event_count` says how much record stands behind the page.
    """
    assert "criterion_ids" in read(RECOMMENDATION_TAB), "evidence lost its criteria"
    detail = read(WEB / "pages" / "CaseDetail.tsx")
    assert "input_sha256" in detail
    assert "audit_event_count" in detail


def test_a_self_declared_reviewer_identity_is_labelled_as_such() -> None:
    """`LEGACY_CALLER_SUPPLIED` means the calling system asserted the identity, not that
    a person authenticated (OD-43).

    Rendering it identically to an authenticated identity would misrepresent the audit
    trail in exactly the situation the trail exists for.
    """
    source = read(REVIEW_TAB)
    assert "LEGACY_CALLER_SUPPLIED" in source
    assert "not authenticated" in source


# --------------------------------------------------------------------------- D8


def test_the_console_declares_the_servers_error_envelope() -> None:
    """**Regression, defect 8.**

    The console declared `code` and `title`; the server sends `error`, `detail`,
    `request_id` and `case_id`. The category was unavailable to the UI and the request id
    - the one thing a reviewer would quote when asking why an action failed - was never
    shown.
    """
    body = re.search(r"export interface ApiError \{(.+?)\n\}", read(TYPES_TS), re.S)
    assert body, "no ApiError interface found"
    fields = set(re.findall(r"^  (\w+)\??:", body.group(1), re.M))

    assert {"error", "detail", "request_id"} <= fields, f"missing envelope fields: {fields}"
    assert "title" not in fields, "`title` is invented; the server never sends it"
    assert "code" not in fields, "`code` is invented; the category field is `error`"


def test_the_request_id_reaches_the_reviewer() -> None:
    """An id nobody is shown is an id nobody can quote."""
    assert "requestId" in read(WEB / "api" / "client.ts")
    for page in ("CaseDetail.tsx", "NewCase.tsx", "ReviewTab.tsx"):
        source = read(WEB / "pages" / page)
        assert "requestId" in source, f"{page} swallows the request id on error"


# --------------------------------------------------------------------------- the invariant


def test_no_outcome_token_is_computed_in_the_console() -> None:
    """The architecture's central claim, checked on the client too.

    `APPROVE_RECOMMENDED` and `DENY_RECOMMENDED` are produced by `decide()` and rendered
    verbatim. A console that *constructed* one would be a second decision engine, and a
    string comparison against one would be the console re-deriving a decision it was
    handed.
    """
    offenders: list[str] = []
    for path in sorted(WEB.rglob("*.ts*")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for token in ("APPROVE_RECOMMENDED", "DENY_RECOMMENDED"):
                if token in line:
                    offenders.append(f"{path.relative_to(REPO)}:{lineno}")
    assert not offenders, (
        "the console names a decision outcome; outcomes are computed by `decide()` and "
        "displayed, never constructed or compared here: " + "; ".join(offenders)
    )


# --------------------------------------------------------------------------- credentials


AUTH_TS = WEB / "lib" / "auth.ts"

#: Every way a browser page can persist a value past its own lifetime.
PERSISTENCE_APIS = (
    "localStorage",
    "sessionStorage",
    "indexedDB",
    "document.cookie",
)


def console_sources() -> list[Path]:
    return sorted(p for p in WEB.rglob("*") if p.suffix in {".ts", ".tsx"})


def test_no_console_source_persists_anything_to_the_browser() -> None:
    """Credentials are held in memory, and that is checked over the whole tree.

    The console carries two secrets: the caller `x-api-key`, which is long-lived and
    reusable, and the reviewer bearer token, which is what the audit attributes a
    decision to. An earlier build wrote both to `localStorage`, where any script on the
    origin can read them and where they outlive the browser session entirely.

    This is asserted across every file rather than over `auth.ts` alone, because the
    property wanted is "the console persists nothing", and a single `localStorage.setItem`
    added to a page component would satisfy a test that only read the credential module.

    The one exception is the deletion of the key the previous build wrote - see
    `auth.ts`. It is allowed to *remove* and nothing else, so it cannot become a
    read-back path.
    """
    offenders: list[str] = []
    for path in console_sources():
        for line_number, line in enumerate(read(path).splitlines(), start=1):
            if line.lstrip().startswith(("*", "//")):
                continue  # prose about the finding, not a call
            for api in PERSISTENCE_APIS:
                if api not in line:
                    continue
                allowed = path == AUTH_TS and api == "localStorage" and "removeItem" in line
                if not allowed:
                    where = path.relative_to(REPO)
                    offenders.append(f"{where}:{line_number}: {line.strip()}")

    assert not offenders, "the console persists to browser storage:\n" + "\n".join(offenders)


def test_the_credential_module_offers_no_way_to_read_storage_back() -> None:
    """Non-vacuity for the rule above: the exception is a deletion, not a door.

    `removeItem` is permitted in `auth.ts`. If a `getItem` were added beside it the test
    above would still catch it, but only because of the `removeItem in line` clause - a
    reformatting onto two lines would slip past. This asserts the module's shape
    directly instead.
    """
    source = read(AUTH_TS)
    assert "removeItem" in source, "the legacy-credential cleanup was dropped"
    assert "getItem" not in source, "auth.ts reads credentials back out of storage"
    assert "setItem" not in source, "auth.ts writes credentials to storage"


def test_the_settings_page_does_not_tell_the_reviewer_they_are_stored() -> None:
    """The copy is part of the finding.

    The page said the credentials "live only in this browser (localStorage)", which was
    accurate and reassuring at the same time. With nothing persisted, that sentence would
    now be false, and a reviewer who believed it would not know a reload discards them.
    """
    source = read(WEB / "pages" / "Settings.tsx")
    assert "localStorage" not in source
    assert "stored locally" not in source
    assert "in memory" in source, "the page does not say where the credentials live"
