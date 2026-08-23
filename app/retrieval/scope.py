"""A retrieval scope that cannot exist without a policy type.

Before Phase 5, retrieval was scoped by `ResolutionResult.version_ids` - every
resolved version flattened into one list regardless of what layer of authority it
came from. On a corpus of regulations only, that was harmless. Adopting NCDs makes
it a defect: `resolve()` for one HCPCS code can legitimately return a REGULATION
*and* an NCD - that is what `governing` and `ncd_governs_over_lcd` exist for - and
one ANN query over both ranks a statutory-conditions chunk against a
coverage-determination chunk on cosine distance, with no notion that they answer
different questions.

A required `document_type` parameter on the search function would be mandatory but
not *coherent*: the caller could still pass a type and a set of ids that disagree,
and the query would return nothing - fail-closed, but silently, which is the kind
of correctness that looks like a corpus gap for a week.

This makes disagreement unrepresentable instead. A `RetrievalScope` is built only
by `ResolutionResult.scope_for()`, which partitions resolved versions by each
version's *actual* document type, so a scope whose ids belong to a different layer
than its label cannot be constructed.

Empty scopes raise on construction rather than on use, so an empty scope cannot be
*held*. An empty resolution must route to `NEEDS_INFO` through the decision table,
never fall through to a search of everything.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from app.policy.models import DocumentType

__all__ = ["EmptyScopeError", "RetrievalScope"]


class EmptyScopeError(ValueError):
    """Raised when a scope would contain no policy versions.

    Deliberately an error rather than an empty result: an empty scope means
    resolution returned nothing, and that case belongs in the decision table, not
    in a query that would then search the whole corpus.
    """


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    """One policy type, its version ids, and the date they were resolved for.

    `as_of` lives here rather than being passed alongside so that a caller cannot
    supply a date that disagrees with the one resolution used - the scope and its
    temporal context travel together or not at all.
    """

    document_type: DocumentType
    policy_version_ids: frozenset[uuid.UUID]
    as_of: date

    def __post_init__(self) -> None:
        if not self.policy_version_ids:
            raise EmptyScopeError(
                f"a {self.document_type.value} retrieval scope must name at least one "
                "policy version; an unscoped search can return a confidently-cited "
                "inapplicable policy"
            )

    @property
    def ids(self) -> list[uuid.UUID]:
        """Deterministically ordered, so a generated SQL statement is comparable."""
        return sorted(self.policy_version_ids)

    def __str__(self) -> str:
        return f"{self.document_type.value} scope of {len(self.policy_version_ids)} version(s) as of {self.as_of}"
