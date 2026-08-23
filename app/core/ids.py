"""Opaque identifier types.

Distinct ``NewType`` aliases rather than bare ``str`` so that a chunk id cannot be
passed where a case id is expected. mypy enforces this at no runtime cost.
"""

from __future__ import annotations

import uuid
from typing import NewType

CaseId = NewType("CaseId", str)
RequestId = NewType("RequestId", str)
ChunkId = NewType("ChunkId", str)
CriterionId = NewType("CriterionId", str)
FactId = NewType("FactId", str)
PolicyVersionId = NewType("PolicyVersionId", str)


def _new() -> str:
    return uuid.uuid4().hex


def new_case_id() -> CaseId:
    return CaseId(_new())


def new_request_id() -> RequestId:
    return RequestId(_new())


def new_chunk_id() -> ChunkId:
    return ChunkId(_new())


def new_fact_id() -> FactId:
    return FactId(_new())
