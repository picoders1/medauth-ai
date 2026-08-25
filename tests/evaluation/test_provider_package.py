"""The one document that leaves this building.

`data/escalations/r86-provider-package.md` is the only R-86 artefact intended to be sent
to somebody outside the project. Two properties matter more than anything it says:

**It must be self-contained.** The four-file package it replaces referenced its own
siblings by repository path, which a recipient does not have. Seven dangling pointers,
each one a question they would have had to ask before starting.

**It must not disclose the deployment.** No base URL, caller key, credential, model or
host name, and no clinical text. The needles are read from the **live** configuration
rather than written down here - a test that hardcoded them would itself publish what it
exists to protect, which is a mistake this repository has already made once and caught.

The document is **generated** from the committed artefacts, so the third property comes
free: it cannot drift from the evidence. `test_the_package_is_regenerable_and_current`
rebuilds it and compares.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from scripts.build_r86_provider_package import build

pytestmark = [pytest.mark.evaluation, pytest.mark.security]

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "data/escalations/r86-provider-package.md"
SEAL = REPO / "data/escalations/r86-reproducer.manifest.json"
ATTRIBUTION = REPO / "data/escalations/r86-provider-attribution.json"


def text() -> str:
    return PACKAGE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- 1
# Self-contained
# ---------------------------------------------------------------------------


def test_the_package_references_no_repository_path() -> None:
    """The defect it was built to fix, asserted so it cannot come back."""
    import re

    offenders = re.findall(r"`(?:data|docs|eval|scripts|app|tests)/[^`]+`", text())
    assert not offenders, (
        f"the package points at {offenders}, which the recipient does not have. "
        "Every such reference is a question they must ask before starting."
    )


def test_the_package_links_to_no_sibling_document() -> None:
    import re

    links = re.findall(r"\]\(((?:\.\./)?[^)]*\.md)\)", text())
    assert not links, f"the package links to {links}, which travel nowhere"


def test_the_package_carries_the_evidence_rather_than_citing_it() -> None:
    """A recipient must be able to act on this alone."""
    body = text()
    assert "## 1. The question" in body
    # The request shape, the observation, the elimination, the asks, the closure bar.
    for section in (
        "The request, exactly",
        "What we observe",
        "already eliminated",
        "Questions we cannot answer",
        "Evidence that would settle it",
        "What would let us close this",
    ):
        assert section in body, f"the package has no {section!r} section"
    # All eight factorial cells, so the comparison is checkable.
    factorial = json.loads(
        (REPO / "eval/reports/r86-gradient/factorial_results.json").read_text(encoding="utf-8")
    )
    for cell in factorial["cells"]:
        assert f"`{cell}`" in body, f"{cell} is missing from the comparison table"


# --------------------------------------------------------------------------- 2
# Discloses nothing
# ---------------------------------------------------------------------------


def test_the_package_leaks_no_deployment_value() -> None:
    """Needles from the live configuration, never written down here.

    An earlier test in this repository hardcoded the deployment's host and model names
    as the strings it searched for, and would have committed them. Reading them from
    `Settings` also means this follows the deployment instead of going stale.
    """
    from app.config.settings import Settings
    from app.llm.wiring import structured_model_for

    settings = Settings()
    needles = {
        value.lower()
        for value in (
            urlsplit(settings.llm_base_url).hostname or "",
            settings.llm_model,
            structured_model_for(settings),
        )
        if value and len(value) > 3
    }
    assert needles, "no deployment values resolved; this test would pass vacuously"

    body = text().lower()
    leaked = sorted(needle for needle in needles if needle in body)
    assert not leaked, "the package names the deployment verbatim; the convention is a digest"


def test_the_package_carries_no_credential_material() -> None:
    body = text().lower()
    for marker in ("bearer ", "api_key", "api key", "authorization:", "secret"):
        assert marker not in body, f"the package contains {marker!r}"
    # The caller key appears, but only as the salted digest the seal uses.
    digests = json.loads(SEAL.read_text(encoding="utf-8"))["digests"]
    assert digests["caller_key_id"] in text()


def test_the_package_carries_no_clinical_text() -> None:
    """Checked against the actual notes, not against a keyword list.

    The first draft looked for words like "patient" and fired on this document's own
    assurance that it contains **no** patient data. A keyword heuristic cannot tell an
    assurance from a disclosure; the corpus can. Every distinctive phrase from every
    gold note is searched for directly, which is the property that actually matters.
    """
    body = text().lower()

    # Payload labels identify gold cases and must not travel with the letter.
    assert "CASE-" not in text()

    notes: list[str] = []
    for line in (REPO / "data/gold/cases/gold_v2.jsonl").read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        narrative = case.get("input", {}).get("clinical_note") or ""
        if narrative:
            notes.append(narrative)
    assert notes, "no gold narratives loaded; this test would pass vacuously"

    # Six-word windows: long enough to be distinctive, short enough that a partial
    # quotation is still caught.
    leaked: list[str] = []
    for note in notes:
        words = note.lower().split()
        for start in range(0, max(0, len(words) - 6), 3):
            window = " ".join(words[start : start + 6])
            if len(window) > 25 and window in body:
                leaked.append(window)
    assert not leaked, f"the package quotes clinical narrative: {leaked[:3]}"


# --------------------------------------------------------------------------- 3
# Cannot drift from the evidence
# ---------------------------------------------------------------------------


def test_the_package_is_regenerable_and_current() -> None:
    """Generated, not maintained. If an artefact moves, this fails rather than the
    letter quietly describing a system that has changed."""
    assert build() == text(), (
        "the committed package differs from what the builder produces. Re-run "
        "`uv run python scripts/build_r86_provider_package.py --write`."
    )


def test_the_figures_come_from_the_artefacts() -> None:
    """Spot-checked against the sources rather than trusted."""
    body = text()
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    attribution = json.loads(ATTRIBUTION.read_text(encoding="utf-8"))
    failing = attribution["character_economy_analysis"]["failing_cell"]

    assert seal["digests"]["model"] in body
    assert seal["digests"]["schema"] in body
    assert str(seal["request"]["max_tokens"]) in body
    assert str(failing["non_whitespace_chars"]) in body
    assert str(failing["body_chars"]) in body
    assert str(seal["acceptance"]["max_failure_rate"]) in body


def test_the_package_repeats_the_refused_claims() -> None:
    """The letter must be as careful as the register it draws on - a summary is
    exactly where a hedge gets dropped."""
    attribution = json.loads(ATTRIBUTION.read_text(encoding="utf-8"))
    for claim in attribution["r86"]["not_claimed"]:
        assert claim in text(), f"the package drops the refusal of {claim!r}"
    assert attribution["hypothesis_register"]["standing_statement"] in text()


def test_the_package_does_not_ask_the_provider_to_fix_medauth() -> None:
    body = text().lower()
    assert "not** asking you to help us tune" in body or "not asking you to help us tune" in body
    assert "explain and" in body and "fix it" in body


def test_the_package_states_the_closure_bar_and_refuses_to_move_it() -> None:
    body = text()
    assert "will not move that ceiling" in body
    assert "different system" in body
    # The invisible-swap limitation must travel with the letter, not stay behind.
    assert "hashes the model identifier we send" in body
