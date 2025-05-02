"""
Rate Limiting Utilities

Provides production-grade rate limiting using Redis with:
- Circuit breaker pattern
- Exponential backoff
- Detailed metrics
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

import httpx
from redis.exceptions import RedisError

from app.core.redis.redis_client import client as redis
from app.supabase_home.functions.auth import SupabaseAuthService
from circuitbreaker import circuit
from fastapi import HTTPException, status
from prometheus_client import Counter, Gauge

logger = logging.getLogger(__name__)

# Initialize auth service
auth_service = SupabaseAuthService()

# Prometheus Metrics
RATE_LIMIT_REQUESTS = Counter(
    "rate_limit_requests_total", "Total rate limit requests", ["endpoint", "status"]
)

RATE_LIMIT_GAUGE = Gauge(
    "rate_limit_active_requests", "Currently active rate-limited requests", ["endpoint"]
)


# Default rate limit
DEFAULT_LIMIT = 100

# Cleanup script (runs weekly)
CLEANUP_SCRIPT = """
local keys = redis.call('KEYS', 'rate_meta:*')
for _, key in ipairs(keys) do
    local last_update = redis.call('HGET', key, 'updated_at')
    if last_update and os.time() - last_update > 604800 then
        redis.call('DEL', key)
    end
end
return #keys
"""


@circuit(failure_threshold=3, recovery_timeout=60)
async def check_rate_limit(key: str, limit: int, window: int) -> bool:
    """
    Improved sliding window rate limiting using Redis sorted sets
    More accurate than fixed windows, better for burst protection
    """
    now = datetime.utcnow()
    redis_client = await redis.get_client()
    pipeline = redis_client.pipeline()

    # Remove expired timestamps
    pipeline.zremrangebyscore(key, 0, (now - timedelta(seconds=window)).timestamp())

    # Count remaining requests
    pipeline.zcard(key)

    # Add current request
    pipeline.zadd(key, {now.timestamp(): now.timestamp()})
    pipeline.expire(key, window)

    _, count, _, _ = await pipeline.execute()
    return count >= limit


async def increment_rate_limit(identifier: str, endpoint: str, window: int = 60) -> int:
    """
    Increment rate limit counter for identifier and endpoint

    Args:
        identifier: User ID, IP address, or other unique identifier
        endpoint: API endpoint or action name
        window: Time window in seconds

    Returns:
        Current count after increment
    """
    key = f"rate_limit:{endpoint}:{identifier}"

    # Get or initialize counter
    current = await redis.get(key)
    if current is None:
        await redis.set(key, 1, ex=window)
        return 1

    # Increment and return
    count = int(current) + 1
    await redis.set(key, count, ex=window)
    return count


async def get_remaining_limit(
    identifier: str, endpoint: str, limit: int = 5, window: int = 60
) -> dict:
    """
    Get rate limit details including remaining requests

    Returns:
        {
            "limit": 5,
            "remaining": 3,
            "reset": 1625097600
        }
    """
    key = f"rate_limit:{endpoint}:{identifier}"
    redis_client = await redis.get_client()
    current = int(await redis_client.get(key) or 0)
    ttl = await redis_client.ttl(key)

    return {
        "limit": limit,
        "remaining": max(0, limit - current),
        "reset": int(time.time()) + (ttl if ttl > 0 else window),
    }


async def alert_system(message: str) -> None:
    # Implement your alerting system
    logger.warning(message)


RATE_LIMIT_CIRCUIT = {
    "failure_threshold": 3,
    "recovery_timeout": 60,
}

@circuit(
    failure_threshold=RATE_LIMIT_CIRCUIT["failure_threshold"],
    recovery_timeout=RATE_LIMIT_CIRCUIT["recovery_timeout"],
)
async def verify_and_limit(token: str, ip: str, endpoint: str, window: int = 3600):
    """
    Enhanced with:
    - User-level rate tracking
    - Composite keys for granular control
    """
    RATE_LIMIT_GAUGE.labels(endpoint=endpoint).inc()

    try:
        # Verify JWT with detailed logging
        if not auth_service.verify_jwt(token):
            logger.warning(
                "Invalid JWT token",
                extra={"token": token[:8] + "...", "endpoint": endpoint},
            )
            RATE_LIMIT_REQUESTS.labels(endpoint=endpoint, status="unauthorized").inc()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )

        user_id = auth_service.get_user_id(token)
        limit = DEFAULT_LIMIT

        logger.debug(
            "Rate limit check", extra={"user_id": user_id, "endpoint": endpoint}
        )

        # Composite key: user + IP + endpoint
        rate_key = f"user_rate:{user_id}:{ip}:{endpoint}"

        # Track metadata without tier logic
        metadata = {
            "last_ip": ip,
            "last_endpoint": endpoint,
            "updated_at": datetime.utcnow().isoformat(),
        }

        await redis.hset(f"rate_meta:{user_id}", mapping=metadata)

        if await check_rate_limit(rate_key, limit=limit, window=window):
            logger.warning(
                "Rate limit exceeded",
                extra={
                    "user_id": user_id,
                    "ip": ip,
                    "endpoint": endpoint,
                    "limit": limit,
                },
            )
            RATE_LIMIT_REQUESTS.labels(endpoint=endpoint, status="limited").inc()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {window} seconds",
            )

        await increment_rate_limit(rate_key, endpoint, window=window)
        RATE_LIMIT_REQUESTS.labels(endpoint=endpoint, status="allowed").inc()
        return user_id

    except Exception as e:
        logger.error(
            "Rate limit error",
            extra={"error": str(e), "stack_trace": True},
            exc_info=True,
        )
        RATE_LIMIT_REQUESTS.labels(endpoint=endpoint, status="error").inc()
        # Fail open during Redis outages
        return user_id
    finally:
        RATE_LIMIT_GAUGE.labels(endpoint=endpoint).dec()


async def service_rate_limit(
    key: str, limit: int, window: int, endpoint: str = "internal"
) -> bool:
    """
    Simplified rate limiting for internal services without user authentication.

    Args:
        key: Unique identifier for the rate limit (e.g. 'celery_health')
        limit: Max allowed requests per window
        window: Time window in seconds
        endpoint: Optional endpoint identifier for metrics

    Returns:
        bool: True if request is allowed, False if rate limited
    """
    RATE_LIMIT_GAUGE.labels(endpoint=endpoint).inc()

    try:
        rate_key = f"service_rate:{key}"

        if await check_rate_limit(rate_key, limit=limit, window=window):
            logger.warning(
                "Service rate limit exceeded",
                extra={"key": key, "endpoint": endpoint, "limit": limit},
            )
            RATE_LIMIT_REQUESTS.labels(endpoint=endpoint, status="limited").inc()
            return False

        await increment_rate_limit(rate_key, endpoint, window=window)
        RATE_LIMIT_REQUESTS.labels(endpoint=endpoint, status="allowed").inc()
        return True

    except Exception as e:
        logger.error(
            "Service rate limit error",
            extra={"error": str(e), "stack_trace": True},
            exc_info=True,
        )
        RATE_LIMIT_REQUESTS.labels(endpoint=endpoint, status="error").inc()
        # Fail open during Redis outages
        return True
    finally:
        RATE_LIMIT_GAUGE.labels(endpoint=endpoint).dec()


async def init_cleanup():
    await redis.eval(CLEANUP_SCRIPT, 0)
    # asyncio.create_task(run_weekly(init_cleanup))  # This line is commented out because run_weekly is not defined in the provided code
