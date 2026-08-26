"""Deployment settings, from the environment only.

One of two deliberately separate configuration systems (ADR-017):

======== ================================ ==========================================
Settings environment, prefix ``MEDAUTH_``  secrets, URLs, ports, timeouts, flags
Policy   ``config/decision-policy.yaml``   thresholds, ceilings, gate configuration
======== ================================ ==========================================

The split exists because the two have different lifecycles and different risks. A
database URL varies per environment and is uninteresting. An abstention threshold
is identical everywhere, changes clinical behaviour, and must be reviewable in a
diff and traceable from an audit row.

Production **refuses to start** rather than degrade. A process running with
fail-closed disabled, or trusting every peer, is worse than one that will not
start: the failure is loud and immediate instead of silent and clinical.
"""

from __future__ import annotations

import ipaddress
import os
from enum import StrEnum
from functools import lru_cache
from typing import Any, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.errors import ConfigurationError

__all__ = ["ClinicalTextLogging", "Environment", "Settings", "get_settings"]


class Environment(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class ClinicalTextLogging(StrEnum):
    """How much clinical text may reach a log sink. ``FULL`` is development-only."""

    OFF = "off"
    HASHED = "hashed"
    FULL = "full"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEDAUTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        # File-mounted secrets, which is how every secret mechanism that is not "put
        # it in the environment" delivers material: Docker secrets, Kubernetes
        # `Secret` volumes, a Vault agent sidecar, systemd credentials. Each mounts a
        # directory of files named for the variable - `/run/secrets/MEDAUTH_API_KEYS`
        # - which is exactly the convention ADR-019 specified for the production
        # reference and which nothing in this file had implemented.
        #
        # Environment variables are visible in `docker inspect`, in `/proc/<pid>/environ`
        # to anything sharing a namespace, and in a crash dump. A mounted file is not.
        # This does not make files mandatory: unset `MEDAUTH_SECRETS_DIR` and behaviour
        # is exactly as before.
        #
        # **Precedence is the library's: environment beats file.** So a deployment
        # that sets both gets the environment value, silently. Set one. A test asserts
        # this direction so the surprise is recorded rather than discovered.
        #
        # The directory itself is resolved in `__init__`, not here - see below.
        extra="ignore",
        frozen=True,
    )

    def __init__(self, **values: Any) -> None:
        """Resolve the secrets directory from the environment, per instance.

        `MEDAUTH_SECRETS_DIR` is read **here** rather than in `model_config` because a
        class-level `os.environ.get(...)` runs once, at import. That is invisible in a
        container, where the environment is set before the process starts - and it is
        also untestable, since no test can set the variable before the module it is
        importing has been imported.

        Resolving per instance makes the behaviour the same in both worlds and lets a
        test assert it. An explicit `_secrets_dir=` still wins, which is what the
        tests use to point at a temporary directory.
        """
        values.setdefault("_secrets_dir", os.environ.get("MEDAUTH_SECRETS_DIR") or None)
        super().__init__(**values)

    environment: Environment = Environment.DEVELOPMENT

    # --- Model access (through the LLM Firewall, ADR-016) -------------------
    # MEDAUTH holds NO model-provider credential. The firewall holds the upstream
    # key; this is a revocable caller key scoped to that one gateway.
    llm_base_url: str = "http://localhost:8005/v1"
    llm_model: str = "example-model-v1"
    #: The model that serves structured-output roles (intake, per-criterion
    #: adjudication). Separate from `llm_model` because the two are NOT
    #: interchangeable on this deployment, and the difference is measured rather
    #: than assumed: the 2026-08-25 capability probe found the configured
    #: `llm_model` rejects strict `json_schema` outright (502) while supporting
    #: `tool_call`, and the structured-output model does the exact opposite.
    #:
    #: Empty means "use `llm_model`", which is correct only where one model does
    #: both. A deployment where it does not must set this, and readiness says so.
    llm_structured_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_fail_closed: bool = True
    llm_timeout_seconds: float = 60.0
    llm_max_attempts: int = Field(default=3, ge=1, le=10)
    llm_streaming_enabled: bool = False
    llm_max_concurrency: int = Field(default=4, ge=1, le=64)

    # --- Database (ADR-005) --------------------------------------------------
    database_url: str = "postgresql+asyncpg://medauth:medauth@localhost:5435/medauth"

    #: `"key:caller-id,key2:caller-b"`. Empty means the API authenticates nobody and
    #: therefore serves nobody - see app/api/v1/security.py on failing closed.
    api_keys: SecretStr = SecretStr("")

    #: How human reviewers authenticate. `oidc` in production; `development` is refused
    #: there by a validator, because shipping with it enabled would authenticate
    #: everybody who guessed a configured name.
    auth_mode: str = "development"
    #: `"token:principal_id:role,..."`. Development only.
    dev_reviewers: SecretStr = SecretStr("")
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    #: Read `jwks_uri` from the provider's `.well-known/openid-configuration` instead of
    #: configuring it by hand. Keeps a deployment provider-neutral: an issuer, and
    #: nothing vendor-specific.
    oidc_discovery: bool = True
    #: Symmetric (HS256) verification. **Tests only** - the verifier holds the key that
    #: signs, so anyone with this configuration can mint a reviewer token. Production
    #: refuses it below.
    oidc_secret: SecretStr = SecretStr("")
    database_command_timeout_seconds: float = 5.0

    # --- Retrieval (local encoders; never traverse the firewall, ADR-006) ----
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"
    embedding_device: str = "cpu"
    retrieval_top_k: int = Field(default=40, ge=1, le=500)
    rerank_top_n: int = Field(default=8, ge=1, le=100)

    # --- Audit (ADR-013) -----------------------------------------------------
    # A recommendation that cannot be audited is not issued.
    audit_required: bool = True
    retention_enabled: bool = False
    retention_days: int = Field(default=180, ge=1)

    # --- Observability (ADR-018) --------------------------------------------
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    metrics_enabled: bool = True
    clinical_text_logging: ClinicalTextLogging = ClinicalTextLogging.OFF
    log_level: str = "INFO"

    # --- API / reviewer console (ADR-012, ADR-020) ---------------------------
    api_port: int = Field(default=8010, ge=1, le=65535)
    ui_origin: str = "http://localhost:3100"
    trusted_proxies: str = "127.0.0.1/32"

    # --- Policy (ADR-017) ----------------------------------------------------
    decision_policy_file: str = "config/decision-policy.yaml"

    @field_validator("llm_base_url", "database_url", "otel_exporter_otlp_endpoint")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("llm_base_url")
    @classmethod
    def _http_scheme(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("llm_base_url must start with http:// or https://")
        return value.rstrip("/")

    @field_validator("trusted_proxies")
    @classmethod
    def _parseable_cidrs(cls, value: str) -> str:
        for entry in (p.strip() for p in value.split(",") if p.strip()):
            try:
                ipaddress.ip_network(entry, strict=False)
            except ValueError as exc:
                raise ValueError(f"trusted_proxies entry {entry!r} is not a CIDR: {exc}") from exc
        return value

    @property
    def trusted_proxy_networks(self) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
        return tuple(
            ipaddress.ip_network(p.strip(), strict=False)
            for p in self.trusted_proxies.split(",")
            if p.strip()
        )

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @model_validator(mode="after")
    def _enforce_production_boundaries(self) -> Self:
        """Refuse to start rather than serve traffic with a boundary disabled."""
        if not self.is_production:
            return self

        failures: list[str] = []

        if not self.llm_fail_closed:
            failures.append(
                "llm_fail_closed=false: a blocked or failed model call could then "
                "reach a clinical outcome instead of a human (ADR-016)"
            )
        if self.clinical_text_logging is ClinicalTextLogging.FULL:
            failures.append("clinical_text_logging=full: clinical text must never reach a log sink")
        if self.auth_mode != "oidc":
            # A production deployment on the development authenticator would accept
            # any configured token name as a clinical reviewer. That is OD-43 with
            # extra steps, so it fails at startup rather than at the first review.
            failures.append(
                f"auth_mode={self.auth_mode}: human reviewers must authenticate via "
                "OIDC in production; the development adapter authenticates by "
                "configuration and is not an identity"
            )
        if self.auth_mode == "oidc" and not (self.oidc_issuer and self.oidc_audience):
            failures.append(
                "auth_mode=oidc without an issuer and an audience: a token would be "
                "verified against nothing in particular"
            )
        if self.auth_mode == "oidc" and self.oidc_secret.get_secret_value():
            # HS256 means the verifier holds the signing key. Anyone with this config
            # can mint a valid reviewer token, which is a shared password rather than
            # authentication - and it would be recorded in the audit trail as a
            # verified human identity.
            failures.append(
                "oidc_secret is set: symmetric verification means whoever holds this "
                "configuration can mint a reviewer token. Production must verify "
                "asymmetrically, via discovery or an explicit JWKS endpoint"
            )
        if self.auth_mode == "oidc" and not (self.oidc_discovery or self.oidc_jwks_url):
            failures.append(
                "auth_mode=oidc with neither discovery nor a JWKS endpoint: there is "
                "no public key to verify a signature against"
            )
        if not self.llm_api_key.get_secret_value():
            failures.append(
                "llm_api_key is empty: /v1 requires a firewall caller key in production"
            )
        if not self.audit_required:
            failures.append(
                "audit_required=false: a recommendation that cannot be audited is not issued "
                "(ADR-013)"
            )
        if self.llm_streaming_enabled:
            failures.append(
                "llm_streaming_enabled=true: streaming output cannot be schema-validated"
            )

        networks = self.trusted_proxy_networks
        if not networks:
            failures.append("trusted_proxies is empty: reviewer identity could not be established")
        for network in networks:
            if network.prefixlen == 0:
                failures.append(
                    f"trusted_proxies contains {network}: trusting every peer means any client "
                    "can assert any reviewer identity (ADR-012)"
                )

        if failures:
            raise ConfigurationError(
                "refusing to start in production:\n  - " + "\n  - ".join(failures)
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Cached: configuration is read once, at startup."""
    return Settings()
