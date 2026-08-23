"""Ingest a policy corpus into PostgreSQL.

    uv run python scripts/ingest_cms.py --corpus data/cms
    uv run python scripts/ingest_cms.py --corpus tests/fixtures/cms --synthetic
    uv run python scripts/ingest_cms.py --corpus data/cms --no-embed   # structure only

The default source reads documents from a directory, because CMS is unreachable
from some networks and CI has no CMS access at all. Place documents in
``data/cms/`` and run this; nothing about the pipeline changes when they are real
rather than fixtures, except the ``synthetic`` flag in the registry - which travels
into every report derived from the corpus.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config.settings import Settings
from app.core.errors import MedauthError
from app.database.engine import build_engine
from app.observability.logging import configure_logging
from app.policy.acquire import LocalDirectorySource, write_registry
from app.policy.ingest import ingest_all
from app.retrieval.embed import Embedder, SentenceTransformerEmbedder

REPO = Path(__file__).resolve().parents[1]

LICENCE_NOTE = (
    "CMS material is a US Government work. CPT(R) codes and descriptors embedded in it "
    "are AMA-copyrighted: code values are stored, descriptor text is not redistributed."
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="data/cms", help="directory holding documents")
    parser.add_argument(
        "--registry",
        default=None,
        help="default: <corpus>/registry.yaml, so a fixture run cannot misdescribe data/cms/",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="mark documents as CMS-SHAPED rather than CMS; recorded in the registry "
        "and carried into every report derived from this corpus",
    )
    parser.add_argument("--no-embed", action="store_true", help="skip embedding")
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--max-tokens", type=int, default=400)
    parser.add_argument("--overlap-tokens", type=int, default=60)
    args = parser.parse_args()
    registry_path = Path(args.registry or f"{args.corpus.rstrip('/')}/registry.yaml")

    settings = Settings()
    configure_logging(settings)

    source = LocalDirectorySource(
        REPO / args.corpus, synthetic=args.synthetic, licence_note=LICENCE_NOTE
    )

    embedder: Embedder | None = None
    if not args.no_embed:
        embedder = SentenceTransformerEmbedder(
            args.embedding_model or settings.embedding_model,
            device=settings.embedding_device,
        )

    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        documents = list(source.documents())
        print(f"acquired {len(documents)} document(s) from {args.corpus}")

        async with factory() as session:
            # One transaction for the whole corpus: a partially-ingested corpus is
            # not a state the resolver should ever have to reason about.
            result = await ingest_all(
                session,
                documents,
                embedder,
                max_tokens=args.max_tokens,
                overlap_tokens=args.overlap_tokens,
            )
            await session.commit()
    except MedauthError as exc:
        print(f"\ningestion refused:\n{exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    write_registry(result.registry, REPO / registry_path)

    print(
        f"\n  documents        {result.documents}\n"
        f"  versions created {result.versions_created}\n"
        f"  versions skipped {result.versions_skipped}  (unchanged content hash)\n"
        f"  chunks           {result.chunks}\n"
        f"  embedded         {result.embedded}\n"
        f"  registry         {registry_path}"
    )
    for warning in result.warnings:
        print(f"  warning: {warning}")
    if args.synthetic:
        print(
            "\n  NOTE: this corpus is marked SYNTHETIC. Any report derived from it must\n"
            "  state that it was measured on CMS-shaped documents, not real CMS prose."
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
