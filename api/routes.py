"""Wizard REST routes wired to the backend modules.

The one hard rule lives in /api/render: the guardrail runs BEFORE any file is
produced, and if it fails nothing is rendered — the response is blocked=true with
the unverifiable tokens.
"""

from __future__ import annotations

from fastapi import APIRouter

from .agent_routes import router as agent_router
from .application_routes import router as application_router
from .auth_routes import router as auth_router
from .browser_routes import router as browser_router
from .company_finding_routes import router as company_finding_router
from .cv_routes import router as cv_router
from .gmail_routes import router as gmail_router
from .job_board_routes import router as job_board_router
from .run_routes import router as run_router
from .screening_routes import router as screening_router
from .settings_routes import router as settings_router
from .truth_routes import router as truth_router

router = APIRouter(prefix="/api")

# Include order is match order: FastAPI tries routes in registration order, so
# overlapping routes must keep their relative order. /auth/gmail/* overlaps
# /auth/{provider}/*, so gmail must stay before auth.
# tests/test_route_order_snapshot.py locks the route set and the order of
# overlapping pairs.
router.include_router(screening_router)
router.include_router(run_router)
router.include_router(company_finding_router)
router.include_router(truth_router)
router.include_router(cv_router)
router.include_router(application_router)
router.include_router(job_board_router)
router.include_router(settings_router)
router.include_router(gmail_router)
router.include_router(agent_router)
router.include_router(browser_router)
router.include_router(auth_router)
