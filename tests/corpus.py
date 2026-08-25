"""Availability of the restricted CFR corpus, and what to do when it is absent.

`data/cms/*.md` is **deliberately not committed**: the documents carry AMA-copyright
CPT® descriptors, and ADR-003 keeps them out of the tree. Every developer acquires
them locally with `scripts/acquire_ecfr.py`.

That is correct, and it broke CI. Tests that quote the real regulation read those
files, so on a fresh clone - which is exactly what CI is - collection aborted with
`FileNotFoundError` before a single test ran. The suite was green on one machine
and red everywhere else, which is the worst of both: no protection, and no signal
that there was none.

## The rule this module enforces

A corpus-dependent test **skips with a reason naming the missing file**, and never
falls back to a substitute. Substituting a fixture for the authoritative text would
be worse than skipping: the test would pass while verifying a quote against
something CMS never published, and nothing would say so.

Mark such tests `@pytest.mark.corpus`. `tests/conftest.py` skips them
automatically when the corpus is absent, and the reason appears in the report - so
`RUN`, `SKIPPED (corpus unavailable)` and a passing run are three visibly different
outcomes rather than one green tick.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "CORPUS_DIR",
    "REQUIRED_DOCUMENTS",
    "corpus_available",
    "missing_documents",
    "skip_reason",
]

REPO = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO / "data/cms"

#: The documents the committed tests quote. Named explicitly rather than globbed:
#: a glob would report "corpus available" for a directory holding one unrelated
#: file, and the test that needed the other would then fail rather than skip.
REQUIRED_DOCUMENTS = (
    "CFR-410_32-2026-08-13.md",
    "CFR-410_33-2026-08-13.md",
)


def missing_documents() -> tuple[str, ...]:
    """Which required documents are absent. Empty means the corpus is usable."""
    return tuple(name for name in REQUIRED_DOCUMENTS if not (CORPUS_DIR / name).is_file())


def corpus_available() -> bool:
    return not missing_documents()


def skip_reason() -> str:
    """Why the test was skipped, naming the files and how to get them.

    A bare "skipped" is indistinguishable from a test nobody wrote. This says what
    is missing and what to run, so a reader of a CI log can tell an unavailable
    corpus from a broken test.
    """
    missing = missing_documents()
    return (
        f"restricted CFR corpus unavailable: {list(missing)} not in "
        f"{CORPUS_DIR.relative_to(REPO)}. These are NOT committed (AMA-copyright "
        "descriptors, ADR-003). Acquire them with "
        "`uv run python scripts/acquire_ecfr.py` to run this test."
    )
