"""Async database engine and per-request sessions."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# One engine (and therefore one connection pool) for the whole process.
# Opening a new Postgres connection per request would cost ~10-50 ms each time.
engine = create_async_engine(
    settings.database_url,
    pool_size=5,  # connections kept open
    max_overflow=10,  # extra connections allowed under load
    pool_pre_ping=True,  # test a pooled connection before use; replaces dead ones
)

# expire_on_commit=False: after commit, objects keep their loaded values. Otherwise
# reading invoice.status after commit would trigger a lazy refresh, which fails in async.
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, always closed afterwards.

    Commits are explicit in the service layer, because where a transaction ends is
    a business decision (e.g. invoice update + audit log must commit together).
    Anything not committed is rolled back when the session closes.
    """
    async with AsyncSessionLocal() as session:
        yield session
