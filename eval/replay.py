"""Reproducing the semantics gold_v1's labels were computed under.

**This is not an adjudication path.** It lives outside `app/` so that a production
module importing it is a layer-boundary test failure, and everything it produces is
stamped `GOLD_V1_REPLAY`, which `app.policy.semantics_guard` refuses in production.

## Why it has to exist

gold_v1's 156 cases were labelled in the data-foundation phase, before the logic
inventory existed. Every label was computed by `decide()` under an assumed
conjunction - the behaviour Phase 5 has just removed from production, because the
inventory now classifies four of eight policy versions `REVIEW_REQUIRED`.

78 of those 156 cases sit on those four versions. Under production semantics they
route to `HUMAN_REVIEW`, and their recorded labels are unreachable.

There are only three things one can do about that:

1. **Change the labels.** Refused. A frozen split is a record of a completed
   construction; editing it destroys what every earlier measurement was measured
   against (ADR-015, `docs/evaluation/gold-set-protection.md`).
2. **Abandon label reproduction.** That discards half the gold set's usefulness as
   a regression corpus, and it would mean the project could no longer demonstrate
   that its own decision function reproduces its own dataset.
3. **Reproduce the historical assumption explicitly, and refuse it in production.**

This module is (3). The assumption is named rather than defaulted, stamped rather
than anonymous, and refused where it would matter rather than everywhere.

## What this does NOT license

Reproducing a label is not adjudicating a case. A recommendation produced here says
what the system *would have said in the data-foundation phase*; it says nothing
about what it should say now, and the 78 cases it covers cannot be used to validate
an agent. `docs/evaluation/phase5-impact.md` records that as `gold_v1_impact`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.decision.semantics import Attestation, PolicySemantics, SemanticsOrigin
from app.decision.table import CriterionOutcome, assumed_conjunction

__all__ = ["GOLD_V1_MANIFEST", "gold_v1_semantics"]

REPO = Path(__file__).resolve().parents[1]
GOLD_V1_MANIFEST = REPO / "data/gold/manifests/gold_v1.manifest.json"


def _manifest_digest() -> str:
    """Hash the manifest of the set being replayed, not the inventory.

    The attestation must name the artefact that actually justifies the assumption.
    That artefact is gold_v1's manifest - it records the construction these labels
    came from. Naming the inventory instead would be a false claim, and it would
    also let the digest match in production, which is exactly what must not happen.
    """
    return hashlib.sha256(GOLD_V1_MANIFEST.read_bytes()).hexdigest()


def gold_v1_semantics(
    criteria: tuple[CriterionOutcome, ...],
    *,
    policy_id: str,
    policy_version: str,
) -> PolicySemantics:
    """The assumed conjunction gold_v1's labels were computed under.

    Returns an executable value - that is the point - carrying an origin production
    refuses and a digest that cannot match the loaded inventory. Two independent
    reasons for production to reject it, so removing either one does not silently
    open the path.
    """
    return PolicySemantics.assumed(
        policy_id=policy_id,
        policy_version=policy_version,
        logic=assumed_conjunction(criteria, policy_id=policy_id, policy_version=policy_version),
        attestation=Attestation(
            source=str(GOLD_V1_MANIFEST.relative_to(REPO)),
            sha256=_manifest_digest(),
            origin=SemanticsOrigin.GOLD_V1_REPLAY,
        ),
        notes=(
            "HISTORICAL REPLAY: reproduces the assumed conjunction gold_v1 was "
            "labelled under, before the logic inventory existed. Refused in "
            "production. Not an adjudication.",
        ),
    )
