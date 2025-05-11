"""
* Debounce utility using Redis
* DRY, SOLID, CI/CD, and type safety best practices
"""
import logging
import time
from app.core.redis.client import client as redis_client

# ! Debounce: only allow event after interval of inactivity
# todo: Add fail-open logic and Prometheus metrics if needed


async def is_allowed_debounce(key: str, interval: int) -> bool:
    """
    * Debounce: only allow event after interval of inactivity
    Args:
        key (str): Unique identifier for the debounce (user ID, IP, etc.)
        interval (int): Inactivity interval in seconds
    Returns:
        bool: True if allowed, False if debounced
    """
    now = int(time.time())
    try:
        ttl = await redis_client.ttl(key)
        if ttl > 0:
            return False
        await redis_client.set(key, now, ex=interval)
        return True
    except Exception as e:
        # ! Fail-open: If Redis is unavailable, allow the event and log a warning
        import logging
        logging.warning(f"[debounce] Redis unavailable, allowing event (fail-open): {e}")
        return True
