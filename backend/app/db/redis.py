"""Shared async Redis client (cache, rate limiting, health checks)."""

from redis.asyncio import Redis

from app.core.config import settings

# The client manages its own connection pool and connects lazily on first use,
# so creating it at import time is cheap. It is closed in the app's lifespan.
redis_client: Redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
