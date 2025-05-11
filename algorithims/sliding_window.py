"""
* Sliding Window Rate Limiter using Redis
* DRY, SOLID, CI/CD, and type safety best practices
"""
import logging
import time
from app.core.redis.client import client as redis_client

# ! Uses Redis sorted sets for timestamped requests

async def is_allowed_sliding_window(key: str, limit: int, window: int) -> bool:
    """
    * Sliding Window Rate Limiter
    Args:
        key (str): Unique identifier for the rate limit (user ID, IP, etc.)
        limit (int): Max allowed requests per window
        window (int): Window size in seconds
    Returns:
        bool: True if allowed, False if rate limited
    """
    try:
        now = int(time.time())
        min_score = now - window
        p = redis_client._client.pipeline()
        p.zremrangebyscore(key, 0, min_score)
        p.zadd(key, {str(now): now})
        p.zcard(key)
        p.expire(key, window)
        _, _, count, _ = await p.execute()
        return count <= limit
    except Exception as e:
        # ! Fail-open: If Redis is unavailable, allow the event and log a warning
        logging.warning(f"[sliding_window] Redis unavailable, allowing event (fail-open): {e}")
        return True
