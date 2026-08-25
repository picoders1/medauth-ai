"""Real applicability resolution behind the slice's `ApplicabilityPort`.

The counterpart to `app/retrieval/live_port.py`: `resolve()` and two census queries
against the database, handed to the pure classifier in
`app/policy/applicability.py`. The split is the point - filtering happens in SQL
where the one temporal predicate lives, and all six states are decided in a function
with no session, so the state machine is testable as a truth table.

## Why there is a census at all

`resolve()` answers one question: which versions apply to this request, on this
date, in this jurisdiction. When the answer is "none", that single fact cannot tell
a reviewer whether the corpus has never heard of the procedure, or holds a policy
for it that expired last year, or holds one that covers a different contractor's
region. Those are three different next actions, and Phase 15 gives them three
different reasons - which needs the counts before the filters as well as after.

Each census query reuses `in_force_on` and `applies_in_jurisdiction` rather than
re-expressing them, so this module adds no second implementation of "in force on".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.policy import ResolutionPolicy
from app.core.identity import PolicyIdentity, PolicyType
from app.policy.applicability import (
    ApplicabilityFinding,
    ApplicabilityRequest,
    CandidateCensus,
    classify,
)
from app.policy.models import (
    LinkType,
    PolicyCodeLink,
    PolicyDocument,
    PolicyVersion,
)
from app.policy.resolve import ResolutionRequest, resolve
from app.policy.temporal import applies_in_jurisdiction, in_force_on

__all__ = ["LiveApplicability"]


@dataclass
class LiveApplicability:
    """Resolve applicability for one request, against the ingested corpus.

    `designated` is passed per call rather than held, so this adapter cannot quietly
    answer a question about a policy other than the one the caller asked about.
    """

    session: AsyncSession
    policy: ResolutionPolicy
    #: `(request, finding)` for every call, so an experiment record can show what
    #: each case actually resolved to rather than what it was configured to hold.
    findings: list[ApplicabilityFinding] = field(default_factory=list)

    async def applicability_for(
        self, request: ApplicabilityRequest, *, designated: PolicyIdentity
    ) -> ApplicabilityFinding:
        """Never raises. A resolver failure becomes `RESOLUTION_ERROR`, not an exception.

        A raise here would propagate into the slice's generic handler and be
        classified as something else - and "the database was down" must not be
        reported to a reviewer as "no policy covers this procedure".
        """
        if (
            not request.procedure_code.strip()
            or request.code_system is None
            or request.as_of is None
        ):
            # Refused before any query. Nothing to key on, so a census would count
            # the whole corpus or nothing, and either number would be misleading.
            finding = classify(request, designated=designated)
            self.findings.append(finding)
            return finding

        try:
            result = await resolve(
                self.session,
                ResolutionRequest(
                    procedure_code=request.procedure_code,
                    code_system=request.code_system,
                    as_of=request.as_of,
                    jurisdiction=request.jurisdiction,
                    diagnosis_codes=request.diagnosis_codes,
                ),
                self.policy,
            )
            census = await self._census(request)
        except Exception as failure:  # classified, never propagated (port contract)
            finding = classify(
                request, designated=designated, error=f"{type(failure).__name__}: {failure}"
            )
            self.findings.append(finding)
            return finding

        applicable = tuple(
            PolicyIdentity(
                policy_type=PolicyType(version.document_type.value),
                policy_id=version.policy_id,
                version=version.revision_id,
            )
            for version in result.versions
        )
        finding = classify(
            request,
            designated=designated,
            applicable=applicable,
            census=census,
            conflicts=result.conflicts,
        )
        self.findings.append(finding)
        return finding

    async def _census(self, request: ApplicabilityRequest) -> CandidateCensus:
        """Count candidate versions before each filter, in SQL.

        Deliberately does NOT filter by link provenance. The census answers "does
        this corpus know about this procedure at all", and a link that is too weak
        to establish applicability is still evidence that the code is not unheard
        of - reporting `NO_POLICY_LISTS_THE_PROCEDURE` when an inferred link exists
        would overstate what was checked.
        """
        # Both are guaranteed present: `applicability_for` classifies an absent code
        # system or date of service as INSUFFICIENT_INFORMATION before reaching here.
        # Asserted rather than defaulted - a default would turn a missing date into a
        # census taken on some other date, which is the widening direction.
        if request.code_system is None or request.as_of is None:  # pragma: no cover
            raise ValueError("a census requires a code system and a date of service")

        base = (
            select(func.count())
            .select_from(PolicyVersion)
            .join(PolicyDocument, PolicyDocument.id == PolicyVersion.document_id)
            .join(PolicyCodeLink, PolicyCodeLink.policy_version_id == PolicyVersion.id)
            .where(
                PolicyCodeLink.code == request.procedure_code,
                PolicyCodeLink.code_system == request.code_system.value,
                PolicyCodeLink.link_type == LinkType.COVERED_PROCEDURE.value,
            )
        )
        total = (await self.session.execute(base)).scalar_one()
        in_force = (await self.session.execute(base.where(in_force_on(request.as_of)))).scalar_one()
        in_jurisdiction = (
            await self.session.execute(base.where(applies_in_jurisdiction(request.jurisdiction)))
        ).scalar_one()
        return CandidateCensus(
            total=int(total), in_force=int(in_force), in_jurisdiction=int(in_jurisdiction)
        )
