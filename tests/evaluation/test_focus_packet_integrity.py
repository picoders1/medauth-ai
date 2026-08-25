"""The reviewer packet, and the record it feeds, cannot quietly degrade.

Everything here guards an artefact a person outside this project will read and act
on. That makes the failure modes different from the rest of the suite: nothing
crashes, no test goes red on its own, and the damage is that a reviewer answers a
subtly wrong question or that their answer is silently erased afterwards.

Three defects found by hand are pinned here so they cannot recur:

1. the C08 excerpt over-ran the end of (b)(4) and trailed off mid-word
2. `accepted_at` was validated and then discarded, so the record could not show
   that acceptance followed submission
3. `build_focus_decision.py --write` rebuilt the record unconditionally and could
   reset a recorded decision to PENDING
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.review.decision_gate import (
    DecisionGate,
    DecisionStatus,
    GateError,
    ReviewerIdentity,
    SeparationOfDuties,
)
from app.review.focus_impact import FocusOutcome
from app.review.ingest import (
    _MIN_RATIONALE_WORDS,
    SINGLE_PARTY_FIELDS,
    IngestError,
    accept_decision,
    ingest_submission,
    validate_submission,
)

pytestmark = [pytest.mark.evaluation, pytest.mark.security]

#: Only the tests that quote the regulation need the restricted corpus; the
#: ingestion, gate and neutrality tests do not, and marking the whole module
#: would hide them on a clean checkout.
corpus_only = pytest.mark.corpus

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "data/cms/CFR-410_32-2026-08-13.md"
PACKET = REPO / "docs/review/FOCUS-001.md"
IMPACT = REPO / "docs/review/FOCUS-001-impact.md"
INSTRUCTIONS = REPO / "docs/review/FOCUS-001-submission-instructions.md"
RECORD = REPO / "data/review/focus_001_decision.json"
GOLD = REPO / "data/gold/cases/gold_v1.jsonl"
SYNTHETIC = REPO / "data/synthetic/cases/cases.jsonl"

OPTIONS = tuple(outcome.value for outcome in FocusOutcome)
REVIEWER = ReviewerIdentity(reviewer_id="reviewer-1", qualification="coverage analyst")


def _jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)


def _blockquotes(text: str) -> list[str]:
    """Every `>` block in a markdown file, unwrapped and rejoined."""
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith(">"):
            current.append(line[1:].strip())
        elif current:
            blocks.append("\n".join(current).strip())
            current = []
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


# ---------------------------------------------------------------------------
# 1. The excerpt cannot over-run its paragraph
# ---------------------------------------------------------------------------


@corpus_only
def test_every_quoted_regulation_passage_appears_verbatim_in_the_source() -> None:
    """A packet excerpt is evidence. Paraphrase in it is indistinguishable from
    misquotation, and the reviewer has no way to tell which they are reading.

    Only blocks that open like regulation text are checked - the packet also quotes
    the review question and the criteria's own interpretations, which are not
    passages from the CFR.
    """
    source = SOURCE.read_text(encoding="utf-8")
    quoted = [
        b for b in _blockquotes(PACKET.read_text(encoding="utf-8")) if re.match(r"^\(\w+\)", b)
    ]
    assert quoted, "no regulation passages found; the locator is broken, not the packet"

    for block in quoted:
        assert block in source, (
            f"packet quotes text that is not in {SOURCE.name} verbatim: {block[:90]!r}"
        )


@corpus_only
def test_the_c08_excerpt_stops_at_the_end_of_b4() -> None:
    """The defect this pins: the excerpt ran past (b)(4) into the portable x-ray
    section and truncated mid-word at 'place of resid'.

    Checked two ways, because either alone is weak. Substring-of-source catches the
    truncation; the boundary assertion catches an excerpt that swallows the next
    paragraph while still being a genuine substring.
    """
    section = re.search(
        r"^## 5\. Criterion C08.*?(?=^## 6\.)", PACKET.read_text(encoding="utf-8"), re.S | re.M
    )
    assert section is not None
    blocks = _blockquotes(section.group(0))
    assert len(blocks) == 1, "C08 should quote exactly one passage"
    excerpt = blocks[0]

    source = SOURCE.read_text(encoding="utf-8")
    b4 = next(
        line for line in source.splitlines() if line.startswith("(4) Supervision requirement")
    )
    assert excerpt == b4, "the C08 excerpt is not exactly paragraph (b)(4)"

    for intruder in ("Portable x-ray services", "(c) Portable", "place of resid"):
        assert intruder not in excerpt, f"the excerpt has over-run into {intruder!r}"


def test_the_excerpt_still_contains_the_criterion_it_illustrates() -> None:
    """The positive control. An empty or unrelated excerpt would pass every
    prohibition above while telling the reviewer nothing."""
    record = next(
        json.loads(line)
        for line in (REPO / "data/criteria/inventory.jsonl").read_text().splitlines()
        if json.loads(line)["criterion_id"] == "42_CFR_410_32_2026_08_13_C08"
    )
    section = re.search(
        r"^## 5\. Criterion C08.*?(?=^## 6\.)", PACKET.read_text(encoding="utf-8"), re.S | re.M
    )
    assert section is not None
    assert record["authoritative_text"] in _blockquotes(section.group(0))[0]


# ---------------------------------------------------------------------------
# 2. accepted_at is persisted, and cannot be omitted
# ---------------------------------------------------------------------------


def _gate() -> DecisionGate:
    return DecisionGate.pending(
        focus_id="FOCUS-001",
        question="q",
        policy_id="42 CFR 410.32",
        policy_version="2026-08-13",
        permitted_decisions=OPTIONS,
        source_references=("docs/review/FOCUS-001.md",),
    )


def _submission(**over: Any) -> dict[str, Any]:
    return {
        "focus_id": "FOCUS-001",
        "reviewer_identity": "reviewer-1",
        "reviewer_qualification": "coverage analyst",
        "decision": FocusOutcome.NARROW_C03_TO_BASELINE.value,
        "rationale": "the floor is determinable from the regulation and the escalation is not",
        "source_reference": "docs/review/FOCUS-001.md",
        "submitted_at": "2026-09-01",
        **over,
    }


def _submitted() -> DecisionGate:
    return ingest_submission(
        _submission(), gate=_gate(), expected_source_references=("docs/review/FOCUS-001.md",)
    )


def test_acceptance_persists_when_it_happened() -> None:
    accepted = accept_decision(
        _submitted(), {"accepted_by": "maintainer", "accepted_at": "2026-09-02"}
    )
    assert accepted.status is DecisionStatus.ACCEPTED
    assert accepted.accepted_at == date(2026, 9, 2)
    assert accepted.review_timestamp == date(2026, 9, 1)


def test_acceptance_without_a_date_is_refused() -> None:
    with pytest.raises(IngestError, match="accepted_at"):
        accept_decision(_submitted(), {"accepted_by": "maintainer"})


def test_acceptance_before_submission_is_refused() -> None:
    with pytest.raises(IngestError, match="cannot predate"):
        accept_decision(_submitted(), {"accepted_by": "maintainer", "accepted_at": "2026-08-31"})


def test_the_same_person_cannot_submit_and_accept() -> None:
    with pytest.raises(IngestError, match="both submitted and accepted"):
        accept_decision(_submitted(), {"accepted_by": "reviewer-1", "accepted_at": "2026-09-02"})


def test_an_accepted_record_round_trips_every_attribution_field() -> None:
    """The record is the deliverable, not the object. A field that survives in
    memory and vanishes on write is worse than one that was never captured - it
    reads as present right up until someone opens the file."""
    accepted = accept_decision(
        _submitted(), {"accepted_by": "maintainer", "accepted_at": "2026-09-02"}
    )
    written = json.loads(
        json.dumps(
            {
                "status": accepted.status.value,
                "reviewer_identity": accepted.reviewer.reviewer_id if accepted.reviewer else None,
                "reviewer_qualification": (
                    accepted.reviewer.qualification if accepted.reviewer else None
                ),
                "reviewer_decision": accepted.reviewer_decision,
                "reviewer_rationale": accepted.reviewer_rationale,
                "submitted_at": accepted.review_timestamp,
                "accepted_at": accepted.accepted_at,
                "accepted_by": accepted.accepted_by,
                "decision_version": accepted.decision_version,
            },
            default=str,
        )
    )
    for field in (
        "status",
        "reviewer_identity",
        "reviewer_qualification",
        "reviewer_decision",
        "reviewer_rationale",
        "submitted_at",
        "accepted_at",
        "accepted_by",
        "decision_version",
    ):
        assert written[field] not in (None, ""), f"{field} was lost on write"
    assert written["submitted_at"] <= written["accepted_at"]


def test_an_accepted_gate_cannot_be_held_without_a_date() -> None:
    """Construction is a route to a value, not only the transitions."""
    with pytest.raises(GateError, match="no acceptance date"):
        DecisionGate(
            focus_id="FOCUS-001",
            question="q",
            policy_id="p",
            policy_version="v",
            permitted_decisions=OPTIONS,
            status=DecisionStatus.ACCEPTED,
            reviewer=REVIEWER,
            reviewer_decision=FocusOutcome.SPLIT_C03.value,
            reviewer_rationale="because",
            accepted_by="maintainer",
        )


# ---------------------------------------------------------------------------
# 2b. The ADR-026 single-party exemption is narrow, declared, and marked
# ---------------------------------------------------------------------------


EXEMPTION = {
    "accepted_by": "reviewer-1",
    "accepted_at": "2026-09-02",
    "single_party_acceptance": True,
    "single_party_authority": "ADR-026",
    "single_party_justification": (
        "this is a single-author portfolio system on synthetic data with no second "
        "reviewer available to accept independently"
    ),
}


def test_the_default_is_still_refusal() -> None:
    """The exemption must be asked for. Same-identity acceptance with no declaration
    is refused exactly as before ADR-026 existed."""
    with pytest.raises(IngestError, match="collapses two acts into one"):
        accept_decision(_submitted(), {"accepted_by": "reviewer-1", "accepted_at": "2026-09-02"})


@pytest.mark.parametrize("dropped", SINGLE_PARTY_FIELDS)
def test_every_one_of_the_three_declarations_is_required(dropped: str) -> None:
    """Three separate statements, because one field could be set by someone who had
    not read what they were setting: the opt-in, the authority, and the reason."""
    payload = {k: v for k, v in EXEMPTION.items() if k != dropped}
    with pytest.raises(IngestError, match=dropped):
        accept_decision(_submitted(), payload)


def test_the_exemption_cannot_be_claimed_on_another_authority() -> None:
    """An invented or mistyped ADR is refused rather than accepted on trust.

    Otherwise 'single_party_authority' would be a free-text field that permits
    itself, which is a flag wearing a citation.
    """
    with pytest.raises(IngestError, match="does not permit single-party"):
        accept_decision(_submitted(), {**EXEMPTION, "single_party_authority": "ADR-999"})


def test_a_truthy_string_is_not_an_opt_in() -> None:
    with pytest.raises(IngestError, match="boolean true"):
        accept_decision(_submitted(), {**EXEMPTION, "single_party_acceptance": "yes"})


def test_an_unstated_reason_is_refused() -> None:
    with pytest.raises(IngestError, match="words"):
        accept_decision(_submitted(), {**EXEMPTION, "single_party_justification": "solo project"})


def test_an_unfilled_template_placeholder_is_refused() -> None:
    """A template copied and not filled in must not be submittable. The fields most
    likely to be left are the identity and the reason - the two carrying the whole
    weight of the record."""
    with pytest.raises(IngestError, match=r"placeholder|boilerplate"):
        accept_decision(
            _submitted(),
            {**EXEMPTION, "single_party_justification": "<<AT LEAST 12 WORDS>>"},
        )
    issues = validate_submission(
        _submission(reviewer_identity="<<YOUR NAME>>"),
        gate=_gate(),
        expected_source_references=("docs/review/FOCUS-001.md",),
    )
    assert any("placeholder" in issue.problem for issue in issues)


def test_the_template_prompts_cannot_become_the_reasoning() -> None:
    """The near-miss this closes.

    `"your reasoning here, at least eight words"` was refused only because it was
    seven words. At nine it would have gone through, and the record would carry a
    prompt where its reasoning belongs - a rubber stamp that reads as an argument.

    Driven from the template files themselves, so instructional text added to a
    template later is caught here rather than discovered in a submission.
    """
    templates = sorted((REPO / "data/review/payloads").glob("*.template.json"))
    assert templates, "no templates found; the locator is broken, not the guard"

    # Only the field prompts - the `<< >>` values a reviewer is meant to replace.
    # `_README` is documentation about the file rather than a candidate answer, and
    # blocklisting prose that nobody would paste into a rationale would make this
    # brittle without making it stronger.
    prompts: list[str] = []
    for path in templates:
        for key, value in json.loads(path.read_text(encoding="utf-8")).items():
            if key.startswith("_") or not isinstance(value, str):
                continue
            if "<<" in value and len(value.split()) >= _MIN_RATIONALE_WORDS:
                prompts.append(value.replace("<<", "").replace(">>", ""))
    assert prompts, "no long instructional strings in the templates to test against"

    for prompt in prompts:
        issues = validate_submission(
            _submission(rationale=prompt),
            gate=_gate(),
            expected_source_references=("docs/review/FOCUS-001.md",),
        )
        assert any(i.field == "rationale" for i in issues), (
            f"template prompt accepted as a rationale: {prompt[:70]!r}"
        )


def test_reasoning_that_merely_mentions_the_source_is_still_accepted() -> None:
    """The positive control. The guard must refuse instructions, not vocabulary.

    A reviewer legitimately writes about the reading and the regulation; a filter
    that tripped on those words would push people into vaguer rationales.
    """
    issues = validate_submission(
        _submission(
            rationale=(
                "the regulation fixes a general-supervision floor and never states "
                "which tests require more, so the applicable level is not determinable "
                "from this reading of the source"
            )
        ),
        gate=_gate(),
        expected_source_references=("docs/review/FOCUS-001.md",),
    )
    assert issues == ()


def test_a_properly_declared_exemption_is_accepted_and_permanently_marked() -> None:
    """The positive control, and the cost. The decision is usable and it says, on its
    face, that the independent-acceptance control did not hold."""
    accepted = accept_decision(_submitted(), EXEMPTION)
    assert accepted.status is DecisionStatus.ACCEPTED
    assert accepted.is_resolved
    assert accepted.separation_of_duties is SeparationOfDuties.SINGLE_PARTY_EXEMPTED
    assert any("ADR-026" in note for note in accepted.notes)
    assert any("no second reviewer" in note for note in accepted.notes)


def test_a_two_party_acceptance_is_not_marked_as_exempted() -> None:
    """The marker must mean something. If it appeared on ordinary acceptances it
    would stop distinguishing the case it exists to flag."""
    accepted = accept_decision(
        _submitted(), {"accepted_by": "maintainer", "accepted_at": "2026-09-02"}
    )
    assert accepted.separation_of_duties is SeparationOfDuties.TWO_PARTY
    assert accepted.notes == ()


def test_the_marker_cannot_be_dropped_to_flatter_the_record() -> None:
    """Construction is a route to a value. A hand-built record claiming TWO_PARTY
    while naming one person for both acts is refused - the exemption's whole cost is
    that it is visible, and a droppable marker is not a cost."""
    with pytest.raises(GateError, match="still claims TWO_PARTY"):
        DecisionGate(
            focus_id="FOCUS-001",
            question="q",
            policy_id="p",
            policy_version="v",
            permitted_decisions=OPTIONS,
            status=DecisionStatus.ACCEPTED,
            reviewer=REVIEWER,
            reviewer_decision=FocusOutcome.SPLIT_C03.value,
            reviewer_rationale="because",
            accepted_by=REVIEWER.reviewer_id,
            accepted_at=date(2026, 9, 2),
        )


def test_the_exemption_relaxes_exactly_one_check() -> None:
    """It removes the same-identity refusal and nothing else. Every other rule still
    applies, so a single-party acceptance is not a general bypass."""
    with pytest.raises(IngestError, match="cannot predate"):
        accept_decision(_submitted(), {**EXEMPTION, "accepted_at": "2026-08-31"})
    with pytest.raises(IngestError, match="accepted_at"):
        accept_decision(_submitted(), {k: v for k, v in EXEMPTION.items() if k != "accepted_at"})
    with pytest.raises(IngestError, match="cannot accept a PENDING"):
        accept_decision(_gate(), EXEMPTION)


def test_there_is_no_separation_state_meaning_unknown() -> None:
    """Two members. A decision either had an independent acceptance or it did not,
    and a record that cannot say which is worse than either answer."""
    assert {s.value for s in SeparationOfDuties} == {"TWO_PARTY", "SINGLE_PARTY_EXEMPTED"}


def test_the_committed_records_marker_matches_who_actually_acted() -> None:
    """**The world changed on 2026-08-24.** This previously asserted `TWO_PARTY`,
    which was true only because nothing had been accepted yet.

    What it checks now cannot go stale: the marker must agree with the identities on
    the record. A decision accepted by its own submitter must say
    `SINGLE_PARTY_EXEMPTED`; one accepted by anybody else must not.
    """
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    if record["accepted_by"] and record["accepted_by"] == record["reviewer_identity"]:
        assert record["separation_of_duties"] == "SINGLE_PARTY_EXEMPTED"
        assert any("ADR-026" in note for note in record["notes"])
    else:
        assert record["separation_of_duties"] == "TWO_PARTY"


# ---------------------------------------------------------------------------
# 3. A recorded decision cannot be rebuilt away
# ---------------------------------------------------------------------------


def _guard() -> Any:
    """Load the builder's guard without making `scripts/` importable.

    `app/` may not import `scripts`, asserted by the layer-boundary test. Loading by
    path keeps that true while still testing the real function rather than a copy.
    """
    path = REPO / "scripts/build_focus_decision.py"
    spec = importlib.util.spec_from_file_location("build_focus_decision", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(status: str) -> str:
    return json.dumps({"focus_id": "FOCUS-001", "status": status}, indent=2) + "\n"


def test_a_byte_identical_rebuild_of_a_pending_record_is_allowed() -> None:
    """The positive control. If the guard refused everything, the refusals below
    would prove nothing about a working mechanism."""
    module = _guard()
    same = _record("PENDING")
    module.refuse_destructive_rebuild(same, same, archive_to=None)


def test_a_first_build_with_no_existing_record_is_allowed() -> None:
    module = _guard()
    module.refuse_destructive_rebuild(None, _record("PENDING"), archive_to=None)


@pytest.mark.parametrize("status", ["SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED"])
def test_a_rebuild_over_an_answered_decision_is_refused(status: str) -> None:
    """Every status in which a person has acted. Parameterised so a new answered
    state cannot be added without deciding whether it is protected."""
    module = _guard()
    with pytest.raises(module.DecisionResetRefused, match=status):
        module.refuse_destructive_rebuild(_record(status), _record("PENDING"), archive_to=None)


def test_archiving_does_not_rescue_an_answered_decision(tmp_path: Path) -> None:
    """Archival is a workflow for a PENDING record, not a way past the refusal.

    If `--archive-to` unlocked an accepted decision it would be a `--force` flag
    with a longer name, and it would be reached for at exactly the wrong moment.
    """
    module = _guard()
    with pytest.raises(module.DecisionResetRefused):
        module.refuse_destructive_rebuild(
            _record("ACCEPTED"), _record("PENDING"), archive_to=tmp_path / "anywhere.json"
        )


def test_a_changed_pending_record_needs_an_explicit_archive_destination(
    tmp_path: Path,
) -> None:
    module = _guard()
    with pytest.raises(module.DecisionResetRefused, match="archive-to"):
        module.refuse_destructive_rebuild(
            _record("PENDING"), _record("PENDING") + "\n", archive_to=None
        )
    # With a destination it proceeds - history is preserved rather than traded away.
    module.refuse_destructive_rebuild(
        _record("PENDING"), _record("PENDING") + "\n", archive_to=tmp_path / "archive.json"
    )


def test_the_builder_has_no_force_flag() -> None:
    """A flag whose only purpose is to destroy the audit record would be reached for
    when someone is in a hurry, which is when the record matters most."""
    source = (REPO / "scripts/build_focus_decision.py").read_text(encoding="utf-8")
    # The argparse literal, not the prose - the module's docstring says there is no
    # --force, and a scan that tripped on saying so would forbid documenting it.
    assert '"--force"' not in source
    assert "'--force'" not in source
    # The refusal must also not be reachable by simply not looking: every write path
    # goes through the guard.
    assert source.count("OUT_DECISION.write_text") == 1
    assert "refuse_destructive_rebuild(" in source


# ---------------------------------------------------------------------------
# 4. The packet agrees with the data
# ---------------------------------------------------------------------------


def test_the_case_counts_in_the_packet_are_re_derivable() -> None:
    """Re-derived from the datasets, never read back out of the prose that cites
    them. A number that only agrees with itself is not a check."""
    gold, synthetic = _jsonl(GOLD), _jsonl(SYNTHETIC)

    def on_policy(rows: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
        return [r for r in rows if r["expected"]["policy_id"] == "42 CFR 410.32"]

    def cites_c03(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            r
            for r in rows
            if any(c["criterion_id"].endswith("_C03") for c in r["expected"]["criteria"])
        ]

    assert len(cites_c03(on_policy(gold))) == 23
    assert len(on_policy(gold)) == 26
    assert len(cites_c03(on_policy(synthetic))) == 33

    packet = PACKET.read_text(encoding="utf-8")
    assert "**23** of 156" in packet
    assert "23" in json.dumps(len(json.loads(RECORD.read_text())["affected_cases"]))
    assert len(json.loads(RECORD.read_text())["affected_cases"]) == 23


def test_the_packet_and_the_impact_analysis_agree_on_every_outcome() -> None:
    """Two documents a reviewer reads side by side. A disagreement between them is
    a disagreement they have to resolve themselves, with no way to tell which is
    right."""
    impact = json.loads((REPO / "data/review/focus_001_impact.json").read_text())
    by_outcome = {o["outcome"]: o for o in impact["outcomes"]}
    assert set(by_outcome) == set(OPTIONS)

    # The one outcome the analysis says unblocks the policy. Pinned because it
    # regressed silently once: the admissibility gate's eleventh check leaked into
    # `other_blockers`, and NARROW's consequence flipped to "not admissible" for the
    # circular reason that FOCUS-001 was unanswered.
    assert by_outcome["NARROW_C03_TO_BASELINE"]["policy_admissible_after"] is True
    assert impact["other_blockers_after_this_decision"] == []
    for name in ("SPLIT_C03", "LEAVE_C03_NOT_ADJUDICABLE", "OTHER"):
        assert by_outcome[name]["policy_admissible_after"] is False

    doc = IMPACT.read_text(encoding="utf-8")
    assert "| `NARROW_C03_TO_BASELINE` | **yes** |" in doc


def test_no_outcome_blocks_itself() -> None:
    """A blocker that the decision itself resolves must never be reported as a
    remaining one. It reads as 'answering will not help', which is both false and
    the most discouraging thing the analysis could say."""
    impact = json.loads((REPO / "data/review/focus_001_impact.json").read_text())
    for outcome in impact["outcomes"]:
        assert "domain_decisions_resolved" not in outcome["still_blocked_by"]
        assert "no_unresolved_dependency" not in outcome["still_blocked_by"]


# ---------------------------------------------------------------------------
# 4b. The OD-19 packet quotes its source and cannot answer itself
# ---------------------------------------------------------------------------


OD19_PACKET = REPO / "docs/review/OD-19-410.33.md"
OD19_RECORD = REPO / "data/review/od_19_410_33_decision.json"
OD19_SOURCE = REPO / "data/cms/CFR-410_33-2026-08-13.md"


def _od19_builder() -> Any:
    path = REPO / "scripts/build_od19_packet.py"
    spec = importlib.util.spec_from_file_location("build_od19_packet", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@corpus_only
def test_every_od19_provision_is_quoted_verbatim_from_the_source() -> None:
    """The C08 lesson, applied before the packet is handed over rather than after.

    An excerpt is evidence. If it does not appear in the regulation exactly, the
    reviewer is reading something the project wrote about the regulation, and has no
    way to tell which they have.
    """
    source = OD19_SOURCE.read_text(encoding="utf-8")
    quoted = [
        b for b in _blockquotes(OD19_PACKET.read_text(encoding="utf-8")) if re.match(r"^\(\w+\)", b)
    ]
    assert len(quoted) >= 5, "the packet should quote every provision it asks about"
    for block in quoted:
        for line in block.split("\n"):
            assert line in source, f"packet quote is not verbatim in the source: {line[:80]!r}"


def test_a_provision_that_moved_fails_the_build_rather_than_the_packet() -> None:
    """A quote is located at build time, not copied by hand.

    If the regulation is re-acquired and a provision moves or is reworded, the build
    must break. A packet that silently kept the old wording would cite text that no
    longer exists in the version it names.
    """
    module = _od19_builder()
    with pytest.raises(module.PacketBuildError, match="does not appear in the source"):
        module._locate("some other document entirely", {"label": "x", "starts_with": "(z) Nope"})


def test_a_provisions_end_is_declared_never_inferred() -> None:
    """The C08 excerpt over-ran because its end was left to a character count.

    `through` must be found AFTER the opening, or the build fails - a closing phrase
    matched from the start of the document would produce an empty or reversed span.
    """
    module = _od19_builder()
    text = "(a) opening here.\n(b) later.\nclosing phrase."
    quote = module._locate(text, {"label": "x", "starts_with": "(a) opening", "through": "later."})
    assert quote.startswith("(a) opening") and quote.endswith("later.")
    with pytest.raises(module.PacketBuildError, match="closing text not found"):
        module._locate(text, {"label": "x", "starts_with": "(b) later", "through": "opening here."})


def test_the_od19_record_is_unanswered_and_has_no_route_to_an_answer() -> None:
    record = json.loads(OD19_RECORD.read_text(encoding="utf-8"))
    assert record["status"] == "PENDING"
    assert record["is_resolved"] is False
    assert record["blocks_production"] is True
    assert record["reviewer_identity"] is None
    assert record["separation_of_duties"] == "TWO_PARTY"

    # Checked over the AST, not by string search: the builder legitimately NAMES the
    # answered statuses in order to refuse rebuilding over them, and a text scan
    # cannot tell that apart from reaching one.
    source = (REPO / "scripts/build_od19_packet.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    transitions = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } & {"submit", "accept", "reject", "supersede"}
    assert not transitions, f"the packet builder calls {transitions}"

    constructors = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "DecisionGate"
    }
    assert constructors == {"pending"}, f"DecisionGate reached via {constructors}"


def test_the_od19_options_are_closed_and_match_the_packet() -> None:
    """The record and the document a reviewer reads must offer the same choices."""
    record = json.loads(OD19_RECORD.read_text(encoding="utf-8"))
    packet = OD19_PACKET.read_text(encoding="utf-8")
    assert record["permitted_decisions"]
    for option in record["permitted_decisions"]:
        assert f"`{option}`" in packet, f"{option} is in the record but not the packet"


def test_no_code_linked_to_410_33_falls_inside_the_a2_exemption() -> None:
    """**The condition the 410.33 declaration rests on.**

    (a)(2) exempts diagnostic mammography, audiologist-furnished, psychologist
    -furnished and certain physical-therapist tests from every paragraph the five
    criteria are drawn from. The declared logic is a plain conjunction, which would
    OVER-APPLY the requirements to such a case.

    It is safe only because resolution is deterministic by procedure code and no
    code in an exempt category links to this policy. That is a fact about the
    linkage table, not an assumption about the corpus - so it is checked here. **If
    a mammography or audiology code is ever linked to 410.33, this fails and the
    declaration must be revisited before the link ships.**
    """
    links = yaml.safe_load((REPO / "data/linkage/policy_code_links.yaml").read_text())
    rows = links.get("links", links) if isinstance(links, dict) else links
    codes = {r["code"] for r in rows if r.get("policy_id") == "42 CFR 410.33"}
    assert codes, "no codes link to 410.33; resolution could not reach it at all"

    meta = {
        json.loads(line)["code"]: json.loads(line)
        for line in (REPO / "data/linkage/code_metadata.jsonl").read_text().splitlines()
        if line
    }
    exempt = ("mammograph", "audiolog", "psycholog", "physical therap", "electrophysiolog")
    for code in sorted(codes):
        description = json.dumps(meta.get(code, {})).lower()
        hit = [word for word in exempt if word in description]
        assert not hit, (
            f"{code} links to 42 CFR 410.33 and its description matches {hit}, an "
            "(a)(2)-exempt category. The declared conjunction would apply "
            "requirements the regulation exempts it from."
        )


def test_the_410_33_declaration_states_what_it_does_not_settle() -> None:
    """An engineering reading must say it is one.

    The structure is read off the regulation's own wording, on the same terms as
    42 CFR 410.32's declaration. Neither closes OD-19, and a declaration that did
    not say so would let `semantics_declared` read as qualified review.
    """
    logic = (REPO / "data/policy_logic/42-CFR-410.33.yaml").read_text(encoding="utf-8")
    # Whitespace-normalised: these statements live in wrapped comments, and a test
    # that broke on a reflow would be testing the line width.
    flat = re.sub(r"[\s#]+", " ", logic)
    assert "curator: engineering" in flat
    assert "Not a clinician, not a coverage analyst" in flat
    assert "does not close OD-19" in flat
    # The three provisions it declines to settle are named, not glossed over.
    for unresolved in ("(a)(2)", "(c)(2)", "C05"):
        assert unresolved in logic, f"{unresolved} is not addressed in the review notes"


def test_the_od19_question_remains_open_after_the_declaration() -> None:
    """Declaring a shape does not answer whether these are the right criteria.

    `semantics_declared` passing and OD-19 being resolved are different facts, and
    the packet exists precisely to keep them apart.
    """
    record = json.loads(OD19_RECORD.read_text(encoding="utf-8"))
    assert record["status"] == "PENDING"
    assert record["is_resolved"] is False


# ---------------------------------------------------------------------------
# 5. Neutrality
# ---------------------------------------------------------------------------

#: Phrases that would put a thumb on the scale. Deliberately about the *shape* of a
#: recommendation rather than particular words, so a rewrite cannot slip past by
#: choosing a synonym for "recommend".
_STEERING = (
    "we recommend",
    "we suggest",
    "our recommendation",
    "recommended outcome",
    "the best option",
    "preferred option",
    "the obvious choice",
    "should choose",
    "should select",
    "should pick",
    "is the right reading",
    "is the correct reading",
)


@pytest.mark.parametrize("path", [PACKET, IMPACT, INSTRUCTIONS, OD19_PACKET], ids=lambda p: p.name)
def test_the_reviewer_documents_do_not_recommend_an_outcome(path: Path) -> None:
    text = path.read_text(encoding="utf-8").lower()
    for phrase in _STEERING:
        assert phrase not in text, f"{path.name} contains steering language: {phrase!r}"


@pytest.mark.parametrize("path", [PACKET, IMPACT], ids=lambda p: p.name)
def test_every_option_is_presented(path: Path) -> None:
    """Neutrality is not only about what is said. Omitting an option steers harder
    than arguing against it, and is easier to do by accident."""
    text = path.read_text(encoding="utf-8")
    for option in OPTIONS:
        assert option in text, f"{path.name} does not mention {option}"


def test_the_documents_state_that_cost_is_not_an_argument() -> None:
    """The counter-steer. Three of the four outcomes differ mainly in expense, and
    a table of costs with no such statement reads as an argument for the cheap one."""
    for path in (PACKET, IMPACT):
        assert "wrong reason" in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 6. The live record is untouched
# ---------------------------------------------------------------------------


def test_the_committed_decision_is_never_half_attributed() -> None:
    """**The world changed on 2026-08-24: FOCUS-001 was answered and accepted.**

    This asserted the record was PENDING with every field null. That was right until
    a reviewer answered. The invariant that holds in both states, and is the one
    worth guarding, is that attribution is all-or-nothing: a record must never carry
    a decision without a name, or a name without a decision.
    """
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    attribution = (
        "reviewer_identity",
        "reviewer_qualification",
        "reviewer_decision",
        "reviewer_rationale",
        "review_timestamp",
        "submitted_at",
    )
    populated = [f for f in attribution if record[f]]
    assert populated == [] or populated == list(attribution), (
        f"half-attributed record: {populated} are set and the rest are not"
    )

    if record["status"] == "PENDING":
        assert record["is_resolved"] is False
        assert record["blocks_production"] is True
        assert not populated
    else:
        assert populated
        assert record["accepted_by"] and record["accepted_at"]
        assert record["accepted_at"] >= record["submitted_at"]


def test_the_record_carries_every_attribution_key_while_still_pending() -> None:
    """The key set does not depend on the status.

    A record that grows fields as it advances hides a missing one behind 'that
    status does not have it', which is exactly the ambiguity an audit trail exists
    to remove.
    """
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    for field in ("submitted_at", "accepted_at", "accepted_by", "decision_version", "status"):
        assert field in record
