"""Where documents come from, and the provenance record that outlives them.

Acquisition is an **adapter**, not a fetcher. CMS is unreachable from some networks
(a geographic edge block, not a crawl policy - see
docs/architecture/phase-1-implementation.md), and CI has no CMS access and never
will. So the default source reads documents an operator placed on disk, and the
HTTP source exists for environments where the origin is reachable.

Provenance is recorded identically whichever adapter ran - URI, retrieval date,
content hash, licence note, and a ``synthetic`` flag - so ``registry.yaml`` is the
record of what was ingested regardless of what fetched it. That flag is the one
that matters most: it travels into every report derived from the corpus, so a
measurement taken on constructed policy text can never be presented as one taken on
real CMS prose.

The documents themselves are never committed. CPT(R) descriptors embedded in CMS
material are AMA-copyrighted (ADR-003); the registry records provenance, and
``.gitignore`` keeps the corpus out of the repository.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

import structlog
import yaml

from app.core.errors import MedauthError
from app.policy.documents import SourceRef

__all__ = [
    "AcquiredDocument",
    "HttpSource",
    "LocalDirectorySource",
    "RegistryEntry",
    "SourceAdapter",
    "SourceUnavailableError",
    "load_registry",
    "write_registry",
]

log = structlog.get_logger(__name__)

DOCUMENT_SUFFIXES = (".md", ".txt", ".policy")


class SourceUnavailableError(MedauthError):
    """The configured source could not supply documents."""


@dataclass(frozen=True, slots=True)
class AcquiredDocument:
    raw: str
    source: SourceRef


@runtime_checkable
class SourceAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def documents(self) -> Iterator[AcquiredDocument]: ...


def _sha256(text: str) -> str:
    """Hash of the raw bytes as acquired.

    Distinct from :func:`app.core.hashing.content_hash`, which normalizes first.
    This one answers "is this the same file I fetched?"; that one answers "does this
    passage still say the same thing?".
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class LocalDirectorySource:
    """Reads documents an operator placed in a directory. The default."""

    def __init__(
        self, directory: Path | str, *, synthetic: bool = False, licence_note: str = ""
    ) -> None:
        self._directory = Path(directory)
        self._synthetic = synthetic
        self._licence_note = licence_note

    @property
    def name(self) -> str:
        return "local"

    def documents(self) -> Iterator[AcquiredDocument]:
        if not self._directory.is_dir():
            raise SourceUnavailableError(f"corpus directory not found: {self._directory}")

        files = sorted(
            p
            for p in self._directory.rglob("*")
            if p.is_file() and p.suffix.lower() in DOCUMENT_SUFFIXES
        )
        if not files:
            raise SourceUnavailableError(
                f"no documents in {self._directory} (looked for {', '.join(DOCUMENT_SUFFIXES)}). "
                "Place CMS documents there, or point --corpus at a fixture directory."
            )

        for path in files:
            raw = path.read_text(encoding="utf-8")
            yield AcquiredDocument(
                raw=raw,
                source=SourceRef(
                    uri=path.as_posix(),
                    retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, UTC).date(),
                    sha256=_sha256(raw),
                    licence_note=self._licence_note,
                    synthetic=self._synthetic,
                    adapter=self.name,
                ),
            )


class HttpSource:
    """Fetches from registered URLs. Off by default; opt in explicitly.

    Present so the pipeline is complete, not because it is the expected path. It
    fetches only URLs the caller supplies - it does not crawl, and it does not
    discover.
    """

    def __init__(
        self,
        urls: tuple[str, ...],
        *,
        timeout_seconds: float = 30.0,
        user_agent: str = "medauth-ai/0.1 (policy ingestion)",
    ) -> None:
        self._urls = urls
        self._timeout = timeout_seconds
        self._user_agent = user_agent

    @property
    def name(self) -> str:
        return "http"

    def documents(self) -> Iterator[AcquiredDocument]:
        import httpx

        for url in self._urls:
            try:
                response = httpx.get(
                    url,
                    timeout=self._timeout,
                    follow_redirects=True,
                    headers={"user-agent": self._user_agent},
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                # An origin that refuses is reported as-is. There is no retry with a
                # different identity: presenting as something else to get past an
                # access control is not something this pipeline does.
                raise SourceUnavailableError(f"{url}: {type(exc).__name__}: {exc}") from exc

            yield AcquiredDocument(
                raw=response.text,
                source=SourceRef(
                    uri=url,
                    retrieved_at=datetime.now(UTC).date(),
                    sha256=_sha256(response.text),
                    adapter=self.name,
                ),
            )


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    """One line of the provenance record. Committed; the document is not."""

    policy_id: str
    document_type: str
    revision_id: str
    title: str
    source_uri: str
    source_url: str
    retrieved_at: date
    sha256: str
    adapter: str
    synthetic: bool
    licence_note: str = ""
    contamination_risk: str = "none"

    def as_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "document_type": self.document_type,
            "revision_id": self.revision_id,
            "title": self.title,
            "source_uri": self.source_uri,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at.isoformat(),
            "sha256": self.sha256,
            "adapter": self.adapter,
            "synthetic": self.synthetic,
            "licence_note": self.licence_note,
            "contamination_risk": self.contamination_risk,
        }


REGISTRY_HEADER = """\
# Corpus provenance. COMMITTED - the documents it describes are NOT (ADR-003).
#
# CMS material is a US Government work, but CPT(R) codes and descriptors embedded in
# it are AMA-copyrighted, so code values are stored and descriptor text is not
# redistributed here.
#
# `synthetic: true` means the document is CMS-SHAPED, not CMS. Every report derived
# from a corpus containing synthetic documents must state that limitation.
#
# Generated by scripts/ingest_cms.py. Edit the corpus, not this file.
"""


def _portable_uri(uri: str, registry_dir: Path) -> str:
    """Local acquisition paths become registry-relative; URLs pass through.

    The registry is **committed**; the documents it describes are not (ADR-003). So it
    is read on machines that never performed the acquisition, and an absolute path from
    the machine that did is meaningless there - it names a directory layout, not a
    document. It also writes a developer's home directory into a tracked file for no
    benefit.

    Nothing consumes this field: it is provenance for a human, and the *canonical*
    identity is `source_url`, which is already a public URL and is untouched here. The
    `sha256` is what actually identifies the content.

    Relative to the registry's own directory rather than to a repository root, because
    the writer knows where it is writing and `app/` has no business computing the shape
    of a checkout. A path outside that directory, and any URL, is left exactly as it is
    rather than being turned into a chain of `..` that would be no more portable.
    """
    if "://" in uri:
        return uri
    try:
        return Path(uri).resolve().relative_to(registry_dir.resolve()).as_posix()
    except ValueError:
        return uri


def write_registry(entries: list[RegistryEntry], path: Path | str) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "document_count": len(entries),
        "synthetic_count": sum(1 for e in entries if e.synthetic),
        "documents": [
            {**e.as_dict(), "source_uri": _portable_uri(e.source_uri, file.parent)}
            for e in sorted(entries, key=lambda e: (e.policy_id, e.revision_id))
        ],
    }
    file.write_text(
        REGISTRY_HEADER + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    log.info("registry_written", path=str(file), documents=len(entries))


def load_registry(path: Path | str) -> dict[str, object]:
    file = Path(path)
    if not file.is_file():
        return {"documents": []}
    loaded = yaml.safe_load(file.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {"documents": []}
