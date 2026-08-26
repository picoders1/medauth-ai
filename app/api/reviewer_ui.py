"""A reviewer UI foundation, server-rendered. No npm, no build step, no CDN.

## Why not Next.js

The roadmap named Next.js and **R-31** names its cost: an npm supply-chain surface in a
healthcare project. A reviewer UI foundation whose job is to render a queue, a case and
four buttons does not need a package manager, a bundler or a runtime framework, and
adding ~1000 transitive dependencies to display server-owned data would be paying R-31's
price for none of its benefit.

This is Jinja templates over the existing FastAPI app - already a dependency, no
lockfile, no CDN, no client-side state. It is deliberately a **foundation**: if a real
reviewer product later needs interactivity this does not survive, and that trade is
recorded in `docs/architecture/reviewer-ui.md` rather than assumed away.

## What the UI is not allowed to do

**It does not decide anything.** Every action posts to the API, which re-authenticates,
re-authorises in the service layer and writes the audit event. The UI holds no
permission logic; a browser that skipped it would reach exactly the same refusals.

**It never renders a recommendation as a decision.** The AI's draft and the human
disposition are separate blocks with separate headings, and the draft carries the words
"AI-generated recommendation - not a decision" every time it appears. A reviewer
skim-reading must not be able to mistake one for the other, and colour alone would not
survive a monochrome print-out of a case.

**It never hides why a case is here.** The routing explanation is rendered above the
recommendation, not below it, because a reviewer needs to know what question they are
being asked before they see the proposed answer. That ordering is an anti-anchoring
measure, and it is the reason R-04 (automation bias) is on the register.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.v1.routes import CallerDep, ReviewerDep, SessionDep, request_id_for
from app.case.review_view import build_review_view
from app.identity.principal import Permission
from app.identity.qualification import (
    NOT_VERIFIED_NOTICE,
    qualification_of,
    verification_state,
)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

router = APIRouter(prefix="/ui", tags=["reviewer-ui"], include_in_schema=False)


@router.get("/cases/{case_id}", response_class=HTMLResponse)
async def case_detail(
    case_id: str,
    request: Request,
    caller: CallerDep,
    reviewer: ReviewerDep,
    session: SessionDep,
) -> Any:
    """One case, everything a reviewer needs, nothing re-run.

    Authentication and authorization are the same dependencies the API uses. There is
    no UI-only path to this data.
    """
    reviewer.require(Permission.READ_CASE)
    view = await build_review_view(session, case_id, caller_id=caller.caller_id)
    return TEMPLATES.TemplateResponse(
        request,
        "case_detail.html",
        {
            "view": view,
            "reviewer": reviewer,
            "qualification": qualification_of(reviewer),
            "qualification_state": verification_state(reviewer).value,
            "qualification_notice": NOT_VERIFIED_NOTICE,
            "may_override": reviewer.has(Permission.OVERRIDE_RECOMMENDATION),
            "may_finalize": reviewer.has(Permission.FINALIZE_CASE),
            "request_id": request_id_for(request),
        },
    )
