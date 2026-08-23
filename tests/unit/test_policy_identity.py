"""Policy type participates in identity, and the R-62 collision cannot happen.

The scenario every test here circles: a REGULATION and an NCD that share a policy
id, share a version, carry identical text and are in force on the same date. Every
composite key in the project except the database's used to treat them as one
document. These tests make that unrepresentable rather than unlikely.
"""

from __future__ import annotations

import pytest

from app.core.identity import PolicyIdentity, PolicyIdentityError, PolicyType
from app.policy.models import DocumentType, LinkProvenance, LinkReviewStatus

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# The collision
# ---------------------------------------------------------------------------


def test_identical_ids_and_versions_of_different_types_are_different_identities() -> None:
    """The R-62 collision, made impossible at the type level.

    Two policies with the same id and the same version, differing only in type.
    Under a `(policy_id, version)` key they are one thing; under `PolicyIdentity`
    they are two, and no amount of matching ids can merge them.

    The prefix rule means this exact pair cannot occur in practice - which is the
    belt to the type's braces - so the test constructs the collision as far as the
    rules allow and asserts the keys still differ.
    """
    regulation = PolicyIdentity(PolicyType.REGULATION, "42 CFR 410.32", "1")
    ncd = PolicyIdentity(PolicyType.NCD, "NCD 410.32", "1")

    assert regulation.version == ncd.version
    assert regulation.policy_id.endswith("410.32") and ncd.policy_id.endswith("410.32")
    assert regulation != ncd
    assert regulation.key != ncd.key
    assert len({regulation.key, ncd.key}) == 2


def test_a_set_keyed_by_identity_keeps_both_layers() -> None:
    """A dict keyed by identity cannot lose one layer to the other.

    This is the failure mode the eval runners had: `{v.version_id for v in ...}`
    over two layers, where whichever row arrived last silently won the key.
    """
    layers = {
        PolicyIdentity(PolicyType.REGULATION, "42 CFR 410.61", "2026-08-13").key: "regulation",
        PolicyIdentity(PolicyType.NCD, "NCD 410.61", "2026-08-13").key: "coverage",
    }
    assert len(layers) == 2
    assert set(layers.values()) == {"regulation", "coverage"}


def test_type_is_the_first_component_of_the_key() -> None:
    """So a partial key that omits it cannot accidentally match a full one."""
    identity = PolicyIdentity(PolicyType.NCD, "NCD 310.1", "3")
    assert identity.key[0] == "NCD"
    assert identity.key != ("NCD 310.1", "3")
    assert identity.scope_key == ("NCD", "NCD 310.1")


# ---------------------------------------------------------------------------
# The prefix rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("policy_type", "policy_id"),
    [
        (PolicyType.REGULATION, "42 CFR 410.32"),
        (PolicyType.NCD, "NCD 310.1"),
        (PolicyType.LCD, "L34567"),
        (PolicyType.ARTICLE, "A56789"),
    ],
)
def test_a_correctly_prefixed_id_is_accepted(policy_type: PolicyType, policy_id: str) -> None:
    assert PolicyIdentity(policy_type, policy_id, "1").policy_type is policy_type


@pytest.mark.parametrize(
    ("policy_type", "policy_id"),
    [
        (PolicyType.NCD, "42 CFR 410.32"),
        (PolicyType.REGULATION, "NCD 310.1"),
        (PolicyType.NCD, "310.1"),
        (PolicyType.REGULATION, "410.32"),
    ],
)
def test_a_mismatched_prefix_is_refused(policy_type: PolicyType, policy_id: str) -> None:
    """A bare policy id must say which layer of authority it names.

    Without this, a regulation and a coverage determination are distinguishable in
    a log line, a citation or an error message only by whoever wrote them.
    """
    with pytest.raises(PolicyIdentityError, match="prefix"):
        PolicyIdentity(policy_type, policy_id, "1")


def test_an_empty_component_is_refused() -> None:
    with pytest.raises(PolicyIdentityError, match="policy_id is empty"):
        PolicyIdentity(PolicyType.NCD, "   ", "1")
    with pytest.raises(PolicyIdentityError, match="version is empty"):
        PolicyIdentity(PolicyType.NCD, "NCD 310.1", "")


# ---------------------------------------------------------------------------
# Round-tripping and inference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "identity",
    [
        PolicyIdentity(PolicyType.REGULATION, "42 CFR 410.32", "2026-08-13"),
        PolicyIdentity(PolicyType.NCD, "NCD 220.6.5", "3"),
        PolicyIdentity(PolicyType.LCD, "L34567", "R4"),
    ],
)
def test_string_form_round_trips(identity: PolicyIdentity) -> None:
    """Identities travel through JSON as strings; the trip must be lossless."""
    assert PolicyIdentity.parse(str(identity)) == identity


def test_inference_recovers_the_type_from_the_prefix() -> None:
    """A migration aid for artefacts written before type was part of identity."""
    assert PolicyIdentity.infer("42 CFR 410.32", "2026-08-13").policy_type is PolicyType.REGULATION
    assert PolicyIdentity.infer("NCD 310.1", "3").policy_type is PolicyType.NCD


def test_inference_refuses_an_unprefixed_id_rather_than_guessing() -> None:
    """A default here would reintroduce the ambiguity the prefix removes."""
    with pytest.raises(PolicyIdentityError, match="no recognised policy-type prefix"):
        PolicyIdentity.infer("310.1", "3")


def test_parse_refuses_a_malformed_string() -> None:
    for raw in ("", "NCD 310.1", "NOPE:NCD 310.1:3"):
        with pytest.raises(PolicyIdentityError):
            PolicyIdentity.parse(raw)


def test_document_type_is_the_same_object_as_policy_type() -> None:
    """An alias, not a parallel enum - a copy could drift from its original."""
    assert DocumentType is PolicyType
    assert DocumentType.NCD is PolicyType.NCD


# ---------------------------------------------------------------------------
# Link authority
# ---------------------------------------------------------------------------


def test_only_the_source_speaking_for_itself_is_authoritative() -> None:
    """Curation and inference are claims about US, not about the source."""
    assert LinkProvenance.SOURCE_STATED.is_authoritative
    assert not LinkProvenance.HUMAN_CURATED.is_authoritative
    assert not LinkProvenance.ENGINEERING_INFERRED.is_authoritative


def test_inferred_links_are_inadmissible_and_curated_ones_are_not_authoritative() -> None:
    """Two different questions, kept apart.

    `HUMAN_CURATED` may establish applicability and is still not authoritative.
    Refusing it as well would leave the corpus with no resolvable link at all -
    disabling the system rather than making it safer.
    """
    assert LinkProvenance.HUMAN_CURATED.admissible_in_production
    assert LinkProvenance.SOURCE_STATED.admissible_in_production
    assert not LinkProvenance.ENGINEERING_INFERRED.admissible_in_production


def test_review_status_is_a_separate_axis_from_provenance() -> None:
    """Verifying a curated link confirms a reading; it does not make it the source."""
    assert "VERIFIED" in {s.value for s in LinkReviewStatus}
    assert "VERIFIED" not in {p.value for p in LinkProvenance}
    assert "SOURCE_STATED" not in {s.value for s in LinkReviewStatus}
