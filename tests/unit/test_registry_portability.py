"""The committed provenance registry must not carry one machine's filesystem.

`data/cms/registry.yaml` is **committed**; the documents it describes are not
(ADR-003, AMA-copyright descriptors). So it is read on machines that never performed
the acquisition — and it was recording absolute paths from the machine that did,
including a developer's home directory, in a tracked file.

Nothing consumes `source_uri`: it is provenance for a human. The canonical identity is
`source_url`, a public URL, and content identity is the `sha256`. So the field can be
made portable without touching either.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from app.policy.acquire import RegistryEntry, write_registry

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
COMMITTED = REPO / "data/cms/registry.yaml"


def _entry(uri: str) -> RegistryEntry:
    return RegistryEntry(
        policy_id="42 CFR 410.33",
        document_type="REGULATION",
        revision_id="2026-08-13",
        title="A title",
        source_uri=uri,
        source_url="https://www.ecfr.gov/current/title-42/section-410.33",
        retrieved_at=date(2026, 8, 13),
        sha256="0" * 64,
        adapter="local",
        synthetic=False,
    )


def test_a_local_path_is_written_relative_to_the_registry(tmp_path: Path) -> None:
    """The acquisition path becomes a name, not a location."""
    document = tmp_path / "CFR-410_33-2026-08-13.md"
    document.write_text("x", encoding="utf-8")
    registry = tmp_path / "registry.yaml"

    write_registry([_entry(str(document))], registry)

    written = yaml.safe_load(registry.read_text())["documents"][0]
    assert written["source_uri"] == "CFR-410_33-2026-08-13.md"
    assert not written["source_uri"].startswith("/")
    # The canonical identity is untouched - that is the field that means something.
    assert written["source_url"] == "https://www.ecfr.gov/current/title-42/section-410.33"


def test_a_url_source_is_left_exactly_as_it_is(tmp_path: Path) -> None:
    """The HTTP adapter already produces a portable identifier. Do not touch it.

    Without this, a future "make everything relative" would quietly mangle the one
    form of `source_uri` that was already correct.
    """
    registry = tmp_path / "registry.yaml"
    url = "https://www.ecfr.gov/api/versioner/v1/full/2026-08-13/title-42.xml"

    write_registry([_entry(url)], registry)

    assert yaml.safe_load(registry.read_text())["documents"][0]["source_uri"] == url


def test_a_path_outside_the_registry_directory_is_not_mangled(tmp_path: Path) -> None:
    """A `..` chain is no more portable than an absolute path, so it is not produced.

    Left as-is and visible, rather than dressed up as relative. A corpus stored outside
    the registry's directory is an unusual arrangement, and the record should say so
    plainly instead of implying a portability it does not have.
    """
    outside = tmp_path / "elsewhere" / "doc.md"
    outside.parent.mkdir()
    outside.write_text("x", encoding="utf-8")
    registry = tmp_path / "corpus" / "registry.yaml"

    write_registry([_entry(str(outside))], registry)

    assert yaml.safe_load(registry.read_text())["documents"][0]["source_uri"] == str(outside)


@pytest.mark.skipif(not COMMITTED.is_file(), reason="data/cms/registry.yaml is absent")
def test_the_committed_registry_carries_no_absolute_path() -> None:
    """**The regression.** This is the artefact that was in the repository.

    Guards the tracked file itself rather than only the writer, because the writer
    being correct does not help if the committed artefact was generated before the fix.
    """
    documents = yaml.safe_load(COMMITTED.read_text())["documents"]
    absolute = [
        d["source_uri"]
        for d in documents
        if "://" not in str(d["source_uri"]) and str(d["source_uri"]).startswith("/")
    ]
    assert not absolute, f"absolute acquisition paths in a committed registry: {absolute}"
