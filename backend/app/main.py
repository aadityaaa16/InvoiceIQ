"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import request_context_middleware, setup_logging
from app.core.rate_limit import limiter
from app.db.redis import redis_client
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Code before `yield` runs at startup, code after it at shutdown."""
    yield
    # Close pooled connections cleanly so Postgres/Redis don't see abrupt disconnects.
    await redis_client.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    """App factory: tests can build a fresh app instead of sharing a global one."""
    setup_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
        # Hide interactive docs in production to avoid advertising the API surface.
        docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
        redoc_url=None,
    )

    # Middleware order: the last one added runs first (outermost). CORS must be
    # outermost so even error responses carry the CORS headers the browser needs.
    app.middleware("http")(request_context_middleware)
    # Browsers block cross-origin requests (frontend :5173 -> API :8000) unless the API
    # explicitly allows that origin. Only the configured frontend origins are allowed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],  # let the frontend read it for bug reports
    )

    app.state.limiter = limiter  # SlowAPI looks the limiter up here
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    return app


app = create_app()
