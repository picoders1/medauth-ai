"""Decision policy: thresholds and gate configuration, from YAML.

The second of the two configuration systems (ADR-017). Everything here changes
**clinical behaviour**, so it is version-controlled, schema-validated, recorded on
every recommendation as ``decision_config_version``, and never silently repaired.

Two properties are enforced structurally rather than by review:

* **Secrets cannot live here.** Any key matching ``*_key``, ``*secret*``,
  ``*token*`` or ``*password*`` fails the load. The failure mode being prevented
  is a credential committed to git, which is irreversible in practice.
* **Invalid policy prevents startup.** A malformed threshold is not defaulted
  away; the process refuses to run.

The decision *table* is deliberately **not** configurable. Rules are the safety
property and live in versioned code with a truth-table suite; only thresholds are
configuration. Making the table configurable would let a deployment reorder rows
6 and 8 - turning missing evidence into a denial - without a code review
(ADR-010).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.errors import ConfigurationError

__all__ = ["AbstentionRules", "AbstentionThresholds", "DecisionPolicy", "load_policy"]

#: A key matching any of these cannot appear anywhere in the policy document.
_SECRET_KEY_PATTERN = re.compile(r"(^|_)(key|secret|token|password|passwd|credential)s?($|_)", re.I)


class AbstentionRules(BaseModel):
    """Hard constraints. Not traded off against anything (ADR-011 stage 1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    require_unique_resolution: bool = True
    require_all_citations_valid: bool = True
    max_contradictions: int = Field(default=0, ge=0)
    min_criteria_coverage: float = Field(default=1.0, ge=0.0, le=1.0)


class AbstentionThresholds(BaseModel):
    """Scored-stage thresholds.

    ``None`` means *not yet calibrated*, and the scored stage is then inert - the
    rule stage alone gates. They stay ``None`` until Phase 6 selects them on the
    dev split by the pre-registered rule. Writing a plausible-looking number here
    before calibration would be a fabricated metric with clinical consequences.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    approve: float | None = Field(default=None, ge=0.0, le=1.0)
    deny: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _deny_is_stricter(self) -> AbstentionThresholds:
        """A wrong denial withholds care; a wrong approval costs money (ADR-011)."""
        if self.approve is not None and self.deny is not None and self.deny <= self.approve:
            raise ValueError(
                f"deny threshold ({self.deny}) must exceed approve ({self.approve}): "
                "denial carries asymmetric harm and needs a stricter bar"
            )
        return self


class ResolutionPolicy(BaseModel):
    """How applicability is decided when several policies apply (ADR-004).

    These are behaviour, not constants, which is why they live in versioned policy
    rather than in code: changing whether two LCDs constitute a conflict changes
    which cases reach a human.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: An NCD outranks an LCD; both are still recorded, and the LCD may add detail.
    ncd_governs_over_lcd: bool = True
    #: Whether a link whose provenance is ENGINEERING_INFERRED may establish
    #: applicability. **False in production, and it must stay false**: an inferred
    #: link rests on resemblance, and applicability from similarity is precisely
    #: what ADR-004 exists to prevent.
    #:
    #: Evaluation may set it true explicitly - the retrieval sets were authored
    #: against links that predate this distinction - but doing so is a declared
    #: choice in a versioned policy file, not a default anyone inherits.
    admit_engineering_inferred_links: bool = False
    #: Two distinct local determinations governing one request is a genuine
    #: conflict, not something to settle by ranking.
    multiple_lcds_are_conflicting: bool = True


class RetrievalPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    top_k: int = Field(default=40, ge=1, le=500)
    rerank_top_n: int = Field(default=8, ge=1, le=100)

    @model_validator(mode="after")
    def _rerank_narrows(self) -> RetrievalPolicy:
        if self.rerank_top_n > self.top_k:
            raise ValueError(f"rerank_top_n ({self.rerank_top_n}) exceeds top_k ({self.top_k})")
        return self


class AdjudicationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_concurrency: int = Field(default=4, ge=1, le=64)
    max_repair_attempts: int = Field(default=2, ge=0, le=5)
    max_criteria_per_case: int = Field(default=64, ge=1, le=512)


class DecisionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    abstention_rules: AbstentionRules = Field(default_factory=AbstentionRules)
    abstention_thresholds: AbstentionThresholds = Field(default_factory=AbstentionThresholds)
    resolution: ResolutionPolicy = Field(default_factory=ResolutionPolicy)
    retrieval: RetrievalPolicy = Field(default_factory=RetrievalPolicy)
    adjudication: AdjudicationPolicy = Field(default_factory=AdjudicationPolicy)

    @property
    def scored_gate_calibrated(self) -> bool:
        return (
            self.abstention_thresholds.approve is not None
            and self.abstention_thresholds.deny is not None
        )


def _reject_secret_keys(node: Any, path: str = "") -> None:
    """Walk the parsed document and refuse anything shaped like a credential."""
    if isinstance(node, dict):
        for key, value in node.items():
            where = f"{path}.{key}" if path else str(key)
            if isinstance(key, str) and _SECRET_KEY_PATTERN.search(key):
                raise ConfigurationError(
                    f"policy key {where!r} looks like a credential. Secrets belong in the "
                    "environment as SecretStr, never in a file that gets committed (ADR-017)."
                )
            _reject_secret_keys(value, where)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _reject_secret_keys(item, f"{path}[{index}]")


def load_policy(path: str | Path) -> DecisionPolicy:
    """Load and validate the decision policy. Raises rather than defaulting."""
    file = Path(path)
    if not file.is_file():
        raise ConfigurationError(f"decision policy not found: {file}")

    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"decision policy {file} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"decision policy {file} must be a mapping, got {type(raw).__name__}"
        )

    _reject_secret_keys(raw)

    try:
        return DecisionPolicy.model_validate(raw)
    except Exception as exc:
        raise ConfigurationError(f"decision policy {file} is invalid: {exc}") from exc
