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
from pathlib import Path

import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.settings import Settings
from app.database.engine import build_engine
from app.policy.models import PolicyCodeLink, PolicyDocument, PolicyVersion

REPO = Path(__file__).resolve().parents[1]


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
                        PolicyVersion.id, PolicyDocument.policy_id, PolicyVersion.revision_id
                    ).join(PolicyDocument, PolicyDocument.id == PolicyVersion.document_id)
                )
            ).all()
            index = {(policy_id, revision): version_id for version_id, policy_id, revision in rows}

            unresolved = [
                f"{link['policy_id']} rev {link['policy_version']}"
                for link in linkage["links"]
                if (link["policy_id"], link["policy_version"]) not in index
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

            await session.execute(text("DELETE FROM policy_code_links"))
            for link in linkage["links"]:
                session.add(
                    PolicyCodeLink(
                        policy_version_id=index[(link["policy_id"], link["policy_version"])],
                        code=link["code"],
                        code_system=link["code_system"],
                        link_type=link["linkage_type"],
                    )
                )
            await session.commit()
            print(f"  {len(linkage['links'])} curated links loaded into the resolution index")
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
