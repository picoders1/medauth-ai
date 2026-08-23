"""Build the reviewer package for NCD coverage status and code linkage (OD-26, OD-27).

Two queues, one script, and neither resolves anything.

**Coverage status.** Every acquired NCD version currently establishes nothing, because
nothing has recorded what it establishes. This assembles the text a reviewer needs -
benefit category, item description, indications and limitations, reasons for denial -
and asks the question, with the decision fields empty.

**Code linkage.** Every NCD link is a curation decision by a non-clinician, because
the CMS record carries no procedure-code field. This lists them for confirmation,
with their provenance and whether production admits them.

**Nothing is pre-filled and nothing is derived.** A `candidate_status` is offered only
where the determination's own text contains an unambiguous coverage phrase, it is
labelled `ENGINEERING_DERIVED`, and `ENGINEERING_DERIVED` is inadmissible as a
coverage conclusion by construction. It exists to give a reviewer a starting point,
not an answer.

Writes `data/review/ncd_status_review.jsonl`, `data/review/ncd_linkage_review.jsonl`
and `data/review/ncd_review_summary.json`.

    uv run python scripts/build_ncd_review_package.py --write
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from app.core.identity import PolicyIdentity, PolicyType
from app.coverage.resolve import CoverageStatus
from app.coverage.status import StatusOrigin, StatusReviewState
from app.policy.models import LinkProvenance, LinkReviewStatus

REPO = Path(__file__).resolve().parents[1]
DOCUMENTS = REPO / "data/coverage/documents"
NCD_LINKAGE = REPO / "data/linkage/ncd_code_links.yaml"
OUT_DIR = REPO / "data/review"

#: Phrases whose presence is unambiguous enough to offer as a STARTING POINT. Not a
#: classifier: no phrase here is read as establishing anything, and a determination
#: matching none of them gets no candidate rather than a guess.
#:
#: Deliberately narrow. "Covered" appears in almost every NCD, including ones that
#: exclude coverage, so it is not a signal on its own.
CANDIDATE_PHRASES: tuple[tuple[str, CoverageStatus], ...] = (
    (r"\bis not covered\b", CoverageStatus.NOT_COVERED),
    (r"\bare not covered\b", CoverageStatus.NOT_COVERED),
    (r"\bnationally non-?covered\b", CoverageStatus.NOT_COVERED),
    (r"\bis covered (?:only )?(?:when|if)\b", CoverageStatus.CONDITIONAL),
    (r"\bcovered (?:only )?(?:when|if)\b", CoverageStatus.CONDITIONAL),
)

REVIEW_QUESTION = (
    "What does this determination establish about national coverage for the item or "
    "service it names - COVERED, NOT_COVERED, CONDITIONAL, or does it address "
    "something other than coverage (NOT_APPLICABLE)? Quote the sentence that "
    "establishes it and name the section it is in."
)


def _candidate(version: dict[str, Any]) -> tuple[CoverageStatus | None, list[dict[str, Any]]]:
    """A starting point and where it came from, or nothing.

    Returns the phrase matches as evidence *references* - section and offsets - so a
    reviewer can go and read them. They are references, not a finding.
    """
    matches: list[dict[str, Any]] = []
    found: CoverageStatus | None = None
    for section, field in (
        ("Indications and Limitations of Coverage", "indications_limitations"),
        ("Reasons for Denial", "reasons_for_denial"),
    ):
        text = str(version.get(field) or "")
        for pattern, status in CANDIDATE_PHRASES:
            for match in re.finditer(pattern, text, re.I):
                matches.append(
                    {
                        "section_path": section,
                        "quote": text[match.start() : match.end()],
                        "span_start": match.start(),
                        "span_end": match.end(),
                        "suggests": status.value,
                    }
                )
                if found is None:
                    found = status
    # Conflicting phrases mean the prose says both things somewhere. Offering one
    # would be picking a side the text does not pick.
    if len({m["suggests"] for m in matches}) > 1:
        return None, matches
    return found, matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    status_rows: list[dict[str, Any]] = []
    for path in sorted(DOCUMENTS.glob("ncd-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for version in payload["versions"]:
            identity = PolicyIdentity(PolicyType.NCD, payload["policy_id"], str(version["version"]))
            candidate, references = _candidate(version)
            status_rows.append(
                {
                    "review_id": f"NCD-STATUS-{payload['ncdid']}-v{version['version']}",
                    "policy_identity": str(identity),
                    "ncd_id": payload["ncdid"],
                    "policy_id": payload["policy_id"],
                    "version_id": version["version"],
                    "title": payload["title"],
                    "temporal_status": version["temporal_status"],
                    "effective_date": version["effective_date"],
                    "end_date": version["end_date"],
                    "effective_date_source": version["effective_date_source"],
                    "source_url": version["source_url"],
                    "retrieved_at": version["retrieved_at"],
                    "content_sha256": version["content_sha256"],
                    "coverage_text": {
                        "benefit_category": version.get("benefit_category", ""),
                        "item_service_description": version.get("item_service_description", ""),
                        "indications_limitations": version.get("indications_limitations", ""),
                        "reasons_for_denial": version.get("reasons_for_denial", ""),
                    },
                    "candidate_status": candidate.value if candidate else None,
                    "candidate_origin": StatusOrigin.ENGINEERING_DERIVED.value,
                    "candidate_basis": (
                        "A narrow phrase scan over the determination's own text. "
                        "ENGINEERING_DERIVED is INADMISSIBLE as a coverage conclusion "
                        "by construction - this is a starting point for a reviewer, "
                        "never a finding. A determination matching no phrase, or "
                        "matching conflicting ones, gets no candidate."
                    ),
                    "evidence_references": references,
                    "permitted_statuses": [s.value for s in CoverageStatus],
                    "permitted_review_states": [s.value for s in StatusReviewState],
                    "review_question": REVIEW_QUESTION,
                    "review_state": StatusReviewState.PENDING.value,
                    "reviewer_status": None,
                    "reviewer_id": None,
                    "reviewer_rationale": None,
                    "reviewed_at": None,
                }
            )

    linkage = yaml.safe_load(NCD_LINKAGE.read_text(encoding="utf-8"))
    default_provenance = str(linkage["default_provenance"])
    linkage_rows: list[dict[str, Any]] = []
    for index, link in enumerate(linkage["links"]):
        provenance = LinkProvenance(str(link.get("provenance", default_provenance)))
        identity = PolicyIdentity.infer(link["policy_id"], str(link["policy_version"]))
        linkage_rows.append(
            {
                "review_id": f"NCD-LINK-{index:03d}",
                "policy_identity": str(identity),
                "policy_id": link["policy_id"],
                "policy_version": str(link["policy_version"]),
                "code": link["code"],
                "code_system": link["code_system"],
                "description": link.get("description", ""),
                "linkage_type": link["linkage_type"],
                "provenance": provenance.value,
                "is_authoritative": provenance.is_authoritative,
                "admissible_in_production": provenance.admissible_in_production,
                "confidence": link["confidence"],
                "rationale": link["rationale"].strip(),
                "curator": linkage["curator"],
                "curator_role": linkage["curator_role"],
                "review_question": (
                    f"Does {link['code']} ({link.get('description', '')}) fall within the "
                    f"subject matter of {identity.policy_id}? Confirm, reject, or say what "
                    "reading question stands in the way."
                ),
                "permitted_review_states": [s.value for s in LinkReviewStatus],
                "review_status": LinkReviewStatus.PENDING.value,
                "reviewer_id": None,
                "reviewer_rationale": None,
                "reviewed_at": None,
            }
        )

    summary = {
        "ncd_versions_awaiting_status_review": len(status_rows),
        "with_a_candidate": sum(1 for r in status_rows if r["candidate_status"]),
        "without_a_candidate": sum(1 for r in status_rows if not r["candidate_status"]),
        "by_temporal_status": dict(
            sorted(Counter(r["temporal_status"] for r in status_rows).items())
        ),
        "links_awaiting_review": len(linkage_rows),
        "links_by_provenance": dict(sorted(Counter(r["provenance"] for r in linkage_rows).items())),
        "links_admissible_in_production": sum(
            1 for r in linkage_rows if r["admissible_in_production"]
        ),
        "authoritative_links": sum(1 for r in linkage_rows if r["is_authoritative"]),
        "prefilled_status_decisions": sum(
            1 for r in status_rows if r["reviewer_status"] is not None
        ),
        "prefilled_linkage_decisions": sum(1 for r in linkage_rows if r["reviewer_id"] is not None),
        "note": (
            "A candidate_status is ENGINEERING_DERIVED and is inadmissible as a "
            "coverage conclusion by construction. No status is derived from a title, "
            "from code linkage, from similarity, or from a model. Until a reviewer "
            "records one, every determination establishes UNKNOWN - which is what the "
            "system reports, not a gap to be filled by inference."
        ),
    }

    print(f"  NCD versions awaiting status review   {len(status_rows)}")
    print(f"    with an engineering candidate       {summary['with_a_candidate']}")
    print(f"    with none (no unambiguous phrase)   {summary['without_a_candidate']}")
    print(f"  links awaiting review                 {len(linkage_rows)}")
    for provenance, count in summary["links_by_provenance"].items():
        admissible = LinkProvenance(provenance).admissible_in_production
        print(f"    {provenance:<22} {count:2d}  ({'resolves' if admissible else 'REFUSED'})")
    print(f"  authoritative links                   {summary['authoritative_links']}")
    print(
        f"  pre-filled reviewer decisions         "
        f"{summary['prefilled_status_decisions'] + summary['prefilled_linkage_decisions']}"
    )

    if args.write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "ncd_status_review.jsonl").write_text(
            "\n".join(json.dumps(r, sort_keys=True) for r in status_rows) + "\n", encoding="utf-8"
        )
        (OUT_DIR / "ncd_linkage_review.jsonl").write_text(
            "\n".join(json.dumps(r, sort_keys=True) for r in linkage_rows) + "\n", encoding="utf-8"
        )
        (OUT_DIR / "ncd_review_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\n  written to {OUT_DIR.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
