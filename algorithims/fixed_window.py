"""
* Fixed Window Rate Limiter using Redis
* DRY, SOLID, CI/CD, and type safety best practices
"""
import logging

from app.core.redis.client import client as redis_client

# ! This implementation assumes Redis is healthy and available.
# todo: Add fail-open logic and Prometheus metrics if needed

async def is_allowed_fixed_window(key: str, limit: int, window: int) -> bool:
    """
    * Fixed Window Rate Limiter
    Args:
        key (str): Unique identifier for the rate limit (user ID, IP, etc.)
        limit (int): Max allowed requests per window
        window (int): Window size in seconds
    Returns:
        bool: True if allowed, False if rate limited
    """
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, window)
        return count <= limit
    except Exception as e:
        # ! Fail-open: If Redis is unavailable, allow the event and log a warning
        logging.warning(f"[fixed_window] Redis unavailable, allowing event (fail-open): {e}")
        return True
