"""Curated transcriptions, and the gate that keeps them honest.

A transcription is a human claim about what a regulation requires. The claim is
only worth anything because it is checked against the regulation - so these tests
are mostly about the checking failing when it should.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from app.policy.criteria import CriterionProvenanceError
from app.policy.transcription import (
    TranscriptionError,
    load_transcription,
    load_transcriptions,
    verify_transcription,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
TRANSCRIPTIONS = REPO / "data" / "criteria" / "transcriptions"


@dataclass(frozen=True)
class FakeSection:
    path: str
    text: str
    page_from: int = 1


SECTIONS = (
    FakeSection(
        "Conditions of Payment",
        "(d) Conditions of Payment. All DMEPOS items require a written "
        "order/prescription for Medicare payment.",
    ),
    FakeSection(
        "General scope",
        "(a) General scope. Medicare Part B pays for durable medical equipment "
        "if the equipment is used in the patient's home.",
    ),
)


@pytest.fixture(scope="module")
def shipped() -> dict[tuple[str, str], object]:
    if not TRANSCRIPTIONS.is_dir():
        pytest.skip("no transcriptions present")
    return load_transcriptions(TRANSCRIPTIONS)  # type: ignore[return-value]


# ------------------------------------------------------------ the shipped set
def test_every_shipped_transcription_loads(shipped: dict) -> None:
    assert shipped, "no transcriptions were loaded"
    for (policy_id, revision_id), transcription in shipped.items():
        assert transcription.declarations, f"{policy_id} {revision_id} declares nothing"
        assert transcription.curator, "a transcription without a curator has no provenance"
        assert isinstance(transcription.curated_at, date)


def test_the_curator_role_disclaims_clinical_expertise(shipped: dict) -> None:
    """The most consequential limitation of the criteria, stated in the artefact
    rather than only in a document nobody opens."""
    for transcription in shipped.values():
        assert "NOT a clinician" in transcription.curator_role


def test_transcriptions_are_unique_per_revision(shipped: dict) -> None:
    """Two curated sets for one revision would make provenance ambiguous."""
    assert len(shipped) == len(set(shipped))


def test_an_exclusion_overlay_is_marked_as_such(shipped: dict) -> None:
    """42 CFR 411.15 declares only exclusions, so it cannot support a standalone
    decision - the decision table would reach its totality guard. The role is
    recorded so a generator can refuse it deliberately rather than by accident."""
    overlays = [t for t in shipped.values() if t.policy_role == "EXCLUSION_OVERLAY"]
    assert overlays, "the exclusion overlay is no longer represented"
    for overlay in overlays:
        assert all(d.criterion_type.value == "EXCLUSION" for d in overlay.declarations)


# --------------------------------------------------------------- verification
def test_a_faithful_transcription_verifies(tmp_path: Path) -> None:
    file = tmp_path / "t.yaml"
    file.write_text(_yaml("All DMEPOS items require a written order", "Conditions of Payment"))
    verified = verify_transcription(
        load_transcription(file),
        SECTIONS,
        document_policy_id="42 CFR 410.38",
        document_revision_id="2026-08-13",
    )
    assert len(verified) == 1
    assert verified[0].source_section == "Conditions of Payment"
    assert verified[0].span_start < verified[0].span_end


@pytest.mark.security
def test_invented_text_is_refused(tmp_path: Path) -> None:
    file = tmp_path / "t.yaml"
    file.write_text(
        _yaml("All DMEPOS items require a notarised affidavit", "Conditions of Payment")
    )
    with pytest.raises(CriterionProvenanceError, match="was not found"):
        verify_transcription(
            load_transcription(file),
            SECTIONS,
            document_policy_id="42 CFR 410.38",
            document_revision_id="2026-08-13",
        )


@pytest.mark.security
def test_correct_text_attributed_to_the_wrong_section_is_refused(tmp_path: Path) -> None:
    """The misattribution case: the quote is real, the citation is not.

    A human spot-check reads the quote, finds it genuine, and passes it - which is
    why this must be caught mechanically.
    """
    file = tmp_path / "t.yaml"
    file.write_text(_yaml("All DMEPOS items require a written order", "General scope"))
    with pytest.raises(CriterionProvenanceError, match="was not found"):
        verify_transcription(
            load_transcription(file),
            SECTIONS,
            document_policy_id="42 CFR 410.38",
            document_revision_id="2026-08-13",
        )


def test_a_transcription_cannot_be_applied_to_another_revision(tmp_path: Path) -> None:
    """Carrying a transcription across revisions is never assumed. 42 CFR 410.38
    was restructured in 2019, and its 2026 criteria do not locate in that text."""
    file = tmp_path / "t.yaml"
    file.write_text(_yaml("All DMEPOS items require a written order", "Conditions of Payment"))
    with pytest.raises(TranscriptionError, match="targets revision"):
        verify_transcription(
            load_transcription(file),
            SECTIONS,
            document_policy_id="42 CFR 410.38",
            document_revision_id="2019-01-01",
        )


def test_a_transcription_cannot_be_applied_to_another_policy(tmp_path: Path) -> None:
    file = tmp_path / "t.yaml"
    file.write_text(_yaml("All DMEPOS items require a written order", "Conditions of Payment"))
    with pytest.raises(TranscriptionError, match="but was verified against"):
        verify_transcription(
            load_transcription(file),
            SECTIONS,
            document_policy_id="42 CFR 410.32",
            document_revision_id="2026-08-13",
        )


def test_a_nonexistent_section_is_refused(tmp_path: Path) -> None:
    file = tmp_path / "t.yaml"
    file.write_text(_yaml("All DMEPOS items require a written order", "Invented Heading"))
    with pytest.raises(CriterionProvenanceError, match="does not exist"):
        verify_transcription(
            load_transcription(file),
            SECTIONS,
            document_policy_id="42 CFR 410.38",
            document_revision_id="2026-08-13",
        )


def test_a_wrong_schema_version_is_refused(tmp_path: Path) -> None:
    file = tmp_path / "t.yaml"
    file.write_text(_yaml("x", "y").replace('schema_version: "1"', 'schema_version: "99"'))
    with pytest.raises(TranscriptionError, match="schema_version"):
        load_transcription(file)


def test_a_transcription_with_no_criteria_is_refused(tmp_path: Path) -> None:
    file = tmp_path / "t.yaml"
    file.write_text(
        'schema_version: "1"\npolicy_id: "x"\nrevision_id: "y"\n'
        "curated_at: 2026-08-23\ncriteria: []\n"
    )
    with pytest.raises(TranscriptionError, match="declares no criteria"):
        load_transcription(file)


def _yaml(text: str, section: str) -> str:
    return (
        'schema_version: "1"\n'
        'policy_id: "42 CFR 410.38"\n'
        'revision_id: "2026-08-13"\n'
        "curator: engineering\n"
        "curator_role: NOT a clinician\n"
        "curated_at: 2026-08-23\n"
        "criteria:\n"
        "  - ordinal: 1\n"
        "    criterion_type: REQUIRED\n"
        "    fact_key: written_order_present\n"
        "    summary: A written order exists\n"
        f"    authoritative_text: {text!r}\n"
        "    normalized_interpretation: A practitioner must have issued a written order.\n"
        f"    source_section: {section!r}\n"
    )
