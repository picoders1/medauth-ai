"""ASGI application: health, readiness, metrics.

Phase 0 exposes no domain routes. What it does establish is the contract every
later route inherits - an OpenAI-shaped error envelope that discloses a category
and a request id and nothing else, and a readiness endpoint whose checks are
classified rather than pooled.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.readiness import evaluate_readiness
from app.api.v1.errors import http_status_for, problem_response
from app.api.v1.routes import router as v1_router
from app.api.v1.security import parse_api_keys
from app.config.policy import load_policy
from app.config.settings import Settings, get_settings
from app.core.errors import MedauthError
from app.core.ids import new_request_id
from app.database.engine import build_engine, build_session_factory
from app.identity.wiring import build_authenticator
from app.observability.logging import configure_logging

__all__ = ["app", "create_app"]

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings: Settings = application.state.settings
    configure_logging(settings)

    # Both raise ConfigurationError rather than degrading. A misconfigured
    # security boundary must fail loudly instead of serving traffic.
    application.state.policy = load_policy(settings.decision_policy_file)
    application.state.engine = build_engine(settings)
    application.state.session_factory = build_session_factory(application.state.engine)

    log.info(
        "startup",
        environment=settings.environment.value,
        policy_version=application.state.policy.version,
        api_port=settings.api_port,
        audit_required=settings.audit_required,
    )
    try:
        yield
    finally:
        await application.state.engine.dispose()
        log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    application = FastAPI(
        title="MEDAUTH AI",
        summary="Evidence-grounded prior-authorization decision support.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if resolved.is_production else "/docs",
        redoc_url=None,
    )
    application.state.settings = resolved
    # Caller identity. Empty means the API refuses every request rather than admitting
    # everyone - an unconfigured deployment must fail closed (app/api/v1/security.py).
    application.state.api_keys = parse_api_keys(resolved.api_keys.get_secret_value())
    # The HUMAN authenticator. `None` means reviews are refused outright - never that
    # the API key stands in for a person (OD-43).
    application.state.authenticator = build_authenticator(resolved)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved.ui_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "content-type"],
    )

    @application.exception_handler(MedauthError)
    async def _domain_error(request: Request, exc: MedauthError) -> JSONResponse:
        """Map a domain error to the status it deserves.

        This used to return **503 for every `MedauthError`** - a case that did not
        exist, a review missing its rationale and an illegal state transition were
        indistinguishable to a caller, and all three read as "the service is down".
        `app/api/v1/errors.py` holds the mapping now, in one place, so a route cannot
        pick its own status.

        The log keeps the type and the request id; the response body carries a message
        we authored. Only unmapped errors are 500, and their detail is fixed text.
        """
        request_id = request.headers.get("x-medauth-request-id") or str(new_request_id())
        status, code = http_status_for(exc)
        log.warning(
            "request_failed",
            error=type(exc).__name__,
            code=code,
            status=status,
            request_id=request_id,
        )
        return problem_response(request, exc, request_id=request_id)

    @application.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        """Liveness only. Deliberately checks no dependency."""
        return {"status": "ok"}

    @application.get("/ready", include_in_schema=False)
    async def ready(request: Request) -> JSONResponse:
        report = await evaluate_readiness(
            settings=request.app.state.settings,
            policy=getattr(request.app.state, "policy", None),
            engine=getattr(request.app.state, "engine", None),
        )
        return JSONResponse(status_code=report.status_code, content=report.as_dict())

    @application.get("/metrics", include_in_schema=False)
    async def metrics() -> Any:
        """Exposition for Prometheus.

        The content type must match the body format. A gateway in the sibling
        project was unscrapeable for seventeen phases because it advertised
        OpenMetrics while emitting text format.
        """
        if not resolved.metrics_enabled:
            return PlainTextResponse("metrics disabled\n", status_code=404)
        return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)

    application.include_router(v1_router)
    return application


app = create_app()
