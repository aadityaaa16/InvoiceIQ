"""Rate limiting with SlowAPI.

Counters live in Redis, so the limit holds across every API instance. With
in-memory counters, 3 instances would each allow 5/minute = 15/minute in total.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Keyed by client IP. Behind a reverse proxy (Azure), uvicorn must run with
# --proxy-headers so the real client IP is used, not the proxy's.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
    enabled=settings.RATE_LIMIT_ENABLED,
)
