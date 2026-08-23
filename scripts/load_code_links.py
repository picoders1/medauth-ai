"""Load the curated policy-to-code linkage into the resolution index.

    uv run python scripts/load_code_links.py

Separate from ingestion on purpose. A regulation carries no code linkage, so the
mapping is a curated artefact with its own provenance and its own review - loading
it as part of document ingestion would make it look like something the document
said.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.settings import Settings
from app.core.identity import PolicyIdentity, PolicyType
from app.database.engine import build_engine
from app.policy.models import (
    LinkProvenance,
    LinkReviewStatus,
    PolicyCodeLink,
    PolicyDocument,
    PolicyVersion,
)

REPO = Path(__file__).resolve().parents[1]

#: The Phase 3 vocabulary, before provenance and review status were separated.
#: Translated rather than rewritten in place: `policy_code_links.yaml` records a
#: curation decision made on a date, and editing its wording now would restate a
#: past judgement in today's terms.
LEGACY_EVIDENCE_CLASS = {
    "AUTHORITATIVE": LinkProvenance.SOURCE_STATED,
    "HUMAN_CURATED": LinkProvenance.HUMAN_CURATED,
    "INFERRED": LinkProvenance.ENGINEERING_INFERRED,
}


def _provenance_of(link: dict[str, Any], default: str) -> LinkProvenance:
    """Read `provenance`, or the legacy `evidence_class`, and refuse anything else.

    Both keys are accepted because two linkage files are in play and one predates
    the vocabulary. What is NOT accepted is a value in neither vocabulary: an
    unrecognised provenance would otherwise fall back to the default, and the
    default is admissible - so a typo would silently promote a refused link into
    one that establishes applicability.
    """
    raw = str(link.get("provenance", link.get("evidence_class", default)))
    if raw in LEGACY_EVIDENCE_CLASS:
        return LEGACY_EVIDENCE_CLASS[raw]
    return LinkProvenance(raw)


async def run(linkage_path: Path, linkage: dict[str, object]) -> int:
    if linkage.get("linkage_class") != "HUMAN_CURATED_ENGINEERING_LINKAGE":
        print("refusing: linkage is not labelled as curated", file=sys.stderr)
        return 1

    settings = Settings()
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            rows = (
                await session.execute(
                    select(
                        PolicyVersion.id,
                        PolicyDocument.policy_id,
                        PolicyVersion.revision_id,
                        PolicyDocument.document_type,
                    ).join(PolicyDocument, PolicyDocument.id == PolicyVersion.document_id)
                )
            ).all()
            # R-62. Keyed by FULL policy identity - type, id and version. Keying
            # by (policy_id, revision) alone was safe only while the corpus held
            # one policy type: two layers could share both, and whichever row the
            # query returned last would silently win the key.
            index = {
                PolicyIdentity(
                    policy_type=PolicyType(document_type), policy_id=policy_id, version=revision
                ).key: version_id
                for version_id, policy_id, revision, document_type in rows
            }

            def _identity(link: dict[str, Any]) -> PolicyIdentity:
                # `infer` recovers the type from the id's prefix and REFUSES an
                # unprefixed id rather than guessing - a guess here would put a
                # curated link on the wrong layer of authority.
                return PolicyIdentity.infer(link["policy_id"], str(link["policy_version"]))

            unresolved = [
                str(_identity(link))
                for link in linkage["links"]
                if _identity(link).key not in index
            ]
            if unresolved:
                # A curated link to a version that is not ingested would silently
                # never fire, and look like a retrieval failure later.
                print(
                    f"refusing: {len(unresolved)} link(s) name un-ingested versions:",
                    file=sys.stderr,
                )
                for item in sorted(set(unresolved)):
                    print(f"  {item}", file=sys.stderr)
                return 1

            # SCOPED delete. A whole-table DELETE was safe with one linkage file
            # and destructive with two: loading the NCD file would silently wipe
            # every CFR link. Only the versions THIS file names are cleared.
            owned = sorted({index[_identity(link).key] for link in linkage["links"]})
            if owned:
                await session.execute(
                    delete(PolicyCodeLink).where(PolicyCodeLink.policy_version_id.in_(owned))
                )

            default_provenance = str(
                linkage.get(
                    "default_provenance",
                    linkage.get("evidence_class_default", LinkProvenance.HUMAN_CURATED.value),
                )
            )
            default_review = str(
                linkage.get("default_review_status", LinkReviewStatus.PENDING.value)
            )
            for link in linkage["links"]:
                provenance = _provenance_of(link, default_provenance)
                session.add(
                    PolicyCodeLink(
                        policy_version_id=index[_identity(link).key],
                        code=link["code"],
                        code_system=link["code_system"],
                        link_type=link["linkage_type"],
                        link_provenance=provenance.value,
                        link_review_status=LinkReviewStatus(
                            str(link.get("review_status", default_review))
                        ).value,
                    )
                )
            await session.commit()
            by_provenance: Counter[str] = Counter(
                _provenance_of(link, default_provenance).value for link in linkage["links"]
            )
            print(f"  {len(linkage['links'])} links loaded into the resolution index")
            for provenance, count in sorted(by_provenance.items()):
                admissible = LinkProvenance(provenance).admissible_in_production
                mark = "resolves" if admissible else "REFUSED by resolution"
                print(f"    {provenance:<22} {count:3d}  ({mark})")
            print(f"  source: {linkage_path.relative_to(REPO)} ({linkage['linkage_class']})")
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linkage", default="data/linkage/policy_code_links.yaml")
    args = parser.parse_args()
    path = REPO / args.linkage
    linkage = yaml.safe_load(path.read_text(encoding="utf-8"))
    return asyncio.run(run(path, linkage))


if __name__ == "__main__":
    sys.exit(main())
