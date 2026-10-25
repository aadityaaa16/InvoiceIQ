"""Health check used by Docker, Azure Container Apps and load balancers.

Lives outside /api/v1 because it is infrastructure, not part of the versioned API.
"""

import asyncio
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.redis import redis_client
from app.db.session import get_db

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_SECONDS = 2.0


async def _check(probe: Awaitable[Any]) -> str:
    """Run one probe with a timeout so a hung dependency cannot hang the health check."""
    try:
        await asyncio.wait_for(probe, timeout=CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception as exc:  # any failure means "unhealthy"; report its type only
        return f"error: {type(exc).__name__}"


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    checks = {
        "database": await _check(db.execute(text("SELECT 1"))),
        "redis": await _check(redis_client.ping()),
    }
    healthy = all(result == "ok" for result in checks.values())
    # 503 tells the orchestrator to stop routing traffic here until we recover.
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )
