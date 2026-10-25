"""Shared test fixtures.

Tests use a real PostgreSQL database (invoiceiq_test) and Redis logical DB 15, so
constraints, indexes and Redis commands behave exactly as in production.
"""

import os

# Must run before any `app` import: settings are read once, at import time.
# Real environment variables override values from .env.
os.environ["ENVIRONMENT"] = "test"
os.environ["POSTGRES_DB"] = "invoiceiq_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-at-least-32-characters")

from collections.abc import AsyncIterator  # noqa: E402

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

import app.models  # noqa: E402, F401  -- register all tables on Base.metadata
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.redis import redis_client  # noqa: E402
from app.db.session import engine, get_db  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def _test_database() -> AsyncIterator[None]:
    """Create the test database if needed and build a fresh schema once per run."""
    admin_url = settings.database_url.replace("postgresql+asyncpg", "postgresql").rsplit("/", 1)[0]
    conn = await asyncpg.connect(f"{admin_url}/postgres")
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", settings.POSTGRES_DB
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{settings.POSTGRES_DB}"')
    finally:
        await conn.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    await redis_client.aclose()
    await engine.dispose()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session whose work is rolled back after each test.

    The outer transaction is never committed. join_transaction_mode="create_savepoint"
    turns the services' session.commit() calls into SAVEPOINT releases inside it,
    so the code under test runs unchanged, and the final rollback undoes everything.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    await redis_client.flushdb()
    yield redis_client
    await redis_client.flushdb()


@pytest.fixture
async def client(db_session: AsyncSession, redis: Redis) -> AsyncIterator[AsyncClient]:
    """HTTP client that calls the app in-process (no server needed).

    ASGITransport does not run the app's lifespan, so the shared Redis client and
    engine are not closed between tests.
    """
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
