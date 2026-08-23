"""Content hashing over normalized text.

Normalizing before hashing is the whole point: a chunk re-ingested with different
whitespace, case or typography hashes **identically**, while a chunk whose words
changed does not. So the hash detects tampering rather than reformatting, which is
what makes it usable as a poisoning signal (threat T-06) instead of a noisy
cache-invalidation flag.
"""

from __future__ import annotations

import hashlib

from app.core.normalize import normalize_text

__all__ = ["content_hash"]


def content_hash(text: str) -> str:
    """SHA-256 of the normalized form of ``text``."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
