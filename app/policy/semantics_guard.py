"""What a given environment will act on, and what it refuses.

`app.decision` may not import settings, read the environment or perform I/O - a
test parses the AST and asserts it. So the decision engine knows only whether the
`PolicySemantics` it holds can execute; it has no way to ask *whose* answer it is
holding. Deciding that is this module's job, and it belongs in `app.policy`, the
layer that already owns both the inventory and the settings.

Two checks, and neither is sufficient alone:

**Origin.** Only `POLICY_LOGIC_INVENTORY` and `DECLARED_LOGIC_FILE` are production
origins. `GOLD_V1_REPLAY` - the assumption gold_v1's labels were computed under -
is refused, and it is written only by `eval/replay.py`, outside `app/` entirely, so
a production module reaching it is a layer-boundary test failure.

**Digest.** An attestation whose `sha256` does not match the inventory actually
loaded at startup is refused. This is what stops "just build a `PolicySemantics`
yourself" from being an equivalent bypass: a hand-written attestation, including a
test fixture's, does not match and does not execute.

**Demotion, never a raise.** A refused value comes back as
`POLICY_SEMANTICS_UNKNOWN` carrying why, so a misconfigured production node routes
cases to a human instead of returning 500s from an adjudication path. Failing
toward the human is the whole design; failing toward an exception would be a
different, worse failure.

The honest limit: a determined in-process caller can defeat an in-process check.
The claim is narrower and true - the *accidental* path fails closed, and the
*deliberate* path is visible in the recommendation, in the audit row, and in grep.
"""

from __future__ import annotations

from app.config.settings import Environment
from app.decision.semantics import PRODUCTION_ORIGINS, PolicySemantics

__all__ = ["admissible"]


def admissible(
    semantics: PolicySemantics,
    *,
    environment: Environment,
    inventory_digest: str,
) -> PolicySemantics:
    """Return `semantics` unchanged, or a value that cannot adjudicate.

    Outside production this is the identity function, deliberately: development and
    evaluation need to reproduce historical semantics, and forbidding that
    everywhere would make gold_v1 unusable as a regression corpus without making
    production any safer.
    """
    if environment is not Environment.PRODUCTION:
        return semantics

    if not semantics.is_executable:
        # Already unable to adjudicate. Nothing to refuse, and re-demoting would
        # append a note about a restriction that did not bite.
        return semantics

    attestation = semantics.attestation
    if attestation is None:
        # Unreachable while the constructors hold - an executable value always
        # carries one. Kept because "unreachable" is a claim about today's code,
        # and this branch costs one line.
        return semantics.demoted("refused in production: executable semantics with no attestation")

    if attestation.origin not in PRODUCTION_ORIGINS:
        return semantics.demoted(
            f"refused in production: semantics origin {attestation.origin.value} is "
            "not a production origin"
        )

    if attestation.sha256 != inventory_digest:
        return semantics.demoted(
            "refused in production: the attestation's digest does not match the "
            "policy logic inventory loaded at startup"
        )

    return semantics
