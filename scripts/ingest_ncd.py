"""Ingest acquired NCD documents into the policy corpus.

Reads the normalised documents `scripts/acquire_ncd.py` wrote and persists them as
`document_type = NCD` alongside the regulation corpus - separate rows, separate
retrieval scopes, never merged (ADR-022, ADR-024).

Three properties this script must not lose:

**Undated versions are stored and unresolvable.** A version whose effective date CMS
never published is persisted with `temporal_status = UNDATED` and a NULL date, so it
is indexed, provenance-preserved, and unreachable by date of service.

**No silent overwrite.** A version already present with different content is an
error, not an update. The corpus records what was acquired; changing it silently
would make an earlier evaluation unreproducible.

**No criteria.** Nothing is transcribed from an NCD, so every ingested version lands
on `SemanticsStatus.NO_CRITERIA` and routes to human review. That is what makes
ingesting a criteria-free coverage layer safe.

    uv run python scripts/ingest_ncd.py --write
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.settings import Settings
from app.core.hashing import content_hash
from app.core.identity import PolicyIdentity, PolicyType
from app.database.engine import build_engine
from app.policy.chunk import chunk_sections
from app.policy.documents import Section
from app.policy.models import (
    PolicyChunk,
    PolicyDocument,
    PolicyVersion,
    TemporalStatus,
    WindowDerivation,
)
from app.retrieval.embed import SentenceTransformerEmbedder

REPO = Path(__file__).resolve().parents[1]
DOCUMENTS = REPO / "data/coverage/documents"

#: Which normalised fields become retrievable text, and under what section name.
#: The names mirror the MCIM field names rather than inventing headings, so a
#: citation's `section_path` says which field of the record it came from.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("Benefit Category", "benefit_category"),
    ("Item/Service Description", "item_service_description"),
    ("Indications and Limitations of Coverage", "indications_limitations"),
    ("Reasons for Denial", "reasons_for_denial"),
    ("Cross Reference", "cross_reference"),
)


def _sections(version: dict[str, Any]) -> tuple[Section, ...]:
    return tuple(
        Section(path=name, text=str(version[field]).strip(), page_from=1, page_to=1)
        for name, field in SECTIONS
        if str(version.get(field) or "").strip()
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", default=str(DOCUMENTS.relative_to(REPO)))
    parser.add_argument("--no-embed", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    paths = sorted((REPO / args.documents).glob("ncd-*.json"))
    if not paths:
        print(f"refusing: no NCD documents under {args.documents}", file=sys.stderr)
        return 1

    embedder = None if args.no_embed else SentenceTransformerEmbedder(Settings().embedding_model)
    engine = build_engine(Settings())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    created = skipped = chunks_written = 0
    conflicts: list[str] = []

    try:
        async with factory() as session:
            for path in paths:
                payload = json.loads(path.read_text(encoding="utf-8"))
                identity_id = payload["policy_id"]

                document = (
                    await session.execute(
                        select(PolicyDocument).where(
                            PolicyDocument.policy_id == identity_id,
                            PolicyDocument.document_type == PolicyType.NCD.value,
                        )
                    )
                ).scalar_one_or_none()
                if document is None:
                    document = PolicyDocument(
                        policy_id=identity_id,
                        document_type=PolicyType.NCD.value,
                        title=payload["title"],
                        source_url=payload["versions"][0]["source_url"],
                        source_authority="CMS",
                        retirement_date_raw=payload.get("retirement_date_raw", ""),
                    )
                    session.add(document)
                    await session.flush()

                for raw in payload["versions"]:
                    revision = str(raw["version"])
                    identity = PolicyIdentity(PolicyType.NCD, identity_id, revision)
                    sections = _sections(raw)
                    body_hash = content_hash("\n\n".join(s.text for s in sections))

                    existing = (
                        await session.execute(
                            select(PolicyVersion).where(
                                PolicyVersion.document_id == document.id,
                                PolicyVersion.revision_id == revision,
                            )
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        if existing.content_sha256 != body_hash:
                            # Never an update. The corpus records what was acquired,
                            # and silently changing it would make an earlier
                            # evaluation unreproducible.
                            conflicts.append(
                                f"{identity}: already ingested with different content "
                                f"({existing.content_sha256[:12]} != {body_hash[:12]})"
                            )
                        else:
                            skipped += 1
                        continue

                    status = TemporalStatus(raw["temporal_status"])
                    version = PolicyVersion(
                        document_id=document.id,
                        revision_id=revision,
                        scope="NATIONAL",
                        jurisdiction=None,
                        effective_date=(
                            date.fromisoformat(raw["effective_date"])
                            if raw["effective_date"]
                            else None
                        ),
                        end_date=(date.fromisoformat(raw["end_date"]) if raw["end_date"] else None),
                        temporal_status=status.value,
                        window_derivation=WindowDerivation(raw["window_derivation"]).value,
                        effective_date_source=raw["effective_date_source"],
                        content_sha256=body_hash,
                        ingested_at=datetime.now(UTC),
                    )
                    session.add(version)
                    await session.flush()
                    created += 1

                    if not sections:
                        continue
                    pieces = chunk_sections(sections)
                    vectors = (
                        embedder.encode_passages([c.text for c in pieces]) if embedder else None
                    )
                    for index, piece in enumerate(pieces):
                        session.add(
                            PolicyChunk(
                                policy_version_id=version.id,
                                section_path=piece.section_path,
                                ordinal=piece.ordinal,
                                page_from=piece.page_from,
                                page_to=piece.page_to,
                                text=piece.text,
                                text_sha256=piece.text_sha256,
                                token_count=piece.token_count,
                                embedding=vectors[index] if vectors else None,
                            )
                        )
                        chunks_written += 1

            if conflicts:
                print("refusing: content changed for already-ingested versions", file=sys.stderr)
                for conflict in conflicts:
                    print(f"  {conflict}", file=sys.stderr)
                await session.rollback()
                return 1

            if args.write:
                await session.commit()
            else:
                await session.rollback()
    finally:
        await engine.dispose()

    print(f"  documents        {len(paths)}")
    print(f"  versions created {created}")
    print(f"  versions skipped {skipped} (already ingested, identical content)")
    print(f"  chunks           {chunks_written}")
    print("\n  written" if args.write else "\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
