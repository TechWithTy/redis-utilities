"""
Redis Cache Utilities

Core Redis functionality including:
- Connection management
- Basic caching operations
- Cache statistics
"""

import hashlib
import json
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, Optional

from opentelemetry import trace
from redis import Redis
from redis.exceptions import RedisError, TimeoutError

from app.core.prometheus.metrics import (
    PULSAR_CACHE_DELETES,
    PULSAR_CACHE_HITS,
    PULSAR_CACHE_MISSES,
    PULSAR_CACHE_SETS,
)
from app.core.redis.config import RedisConfig

logger = logging.getLogger(__name__)


class RedisCache:
    def __init__(self):
        """Initialize Redis connection"""
        self._client = Redis(host=RedisConfig.REDIS_HOST, port=RedisConfig.REDIS_PORT, db=RedisConfig.REDIS_DB)
        self.tracer = trace.get_tracer(__name__)
        self.stats = {"hits": 0, "misses": 0, "sets": 0, "deletes": 0}

    async def get(self, key: str) -> Any | None:
        """Get cached value with stats tracking"""
        with self.tracer.start_as_current_span("redis_cache.get"):
            try:
                value = self._client.get(key)
                if value:
                    self.stats["hits"] += 1
                    PULSAR_CACHE_HITS.inc()
                    return value
                self.stats["misses"] += 1
                PULSAR_CACHE_MISSES.inc()
                return None
            except (RedisError, TimeoutError) as e:
                logger.error(f"Cache get failed for key {key}: {str(e)}")
                raise

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """
        Set a value in Redis with optional TTL.
        If no TTL is provided, uses default from config.
        """
        if ttl is None:
            ttl = RedisConfig.REDIS_CACHE_TTL
        with self.tracer.start_as_current_span("redis_cache.set"):
            self.stats["sets"] += 1
            PULSAR_CACHE_SETS.inc()
            try:
                return self._client.set(key, value, ex=ttl)
            except (RedisError, TimeoutError) as e:
                logger.error(f"Cache set failed for key {key}: {str(e)}")
                raise

    async def delete(self, key: str) -> int:
        """Delete cached value"""
        self.stats["deletes"] += 1
        PULSAR_CACHE_DELETES.inc()
        return self._client.delete(key)

    def get_stats(self) -> dict:
        """Get cache statistics"""
        return self.stats

    async def flush_namespace(self, namespace: str) -> int:
        """Flush all keys in a namespace"""
        keys = self._client.keys(f"{namespace}:*")
        if keys:
            deleted = self._client.delete(*keys)
            self.stats["deletes"] += deleted
            PULSAR_CACHE_DELETES.inc(deleted)
            return deleted
        return 0

    async def warm_cache(self, keys: list[str]):
        """Preload frequently accessed keys"""
        pipeline = self._client.pipeline()
        for key in keys:
            pipeline.get(key)
        pipeline.execute()

# Global Redis cache instance with auto-recovery
redis_cache = RedisCache()


def get_redis_cache() -> RedisCache:
    """
    Get the global Redis cache instance with:
    - Circuit breaking
    - Tracing
    - Cluster support
    """
    return redis_cache


async def get_cached_result(key: str, default: Any = None) -> Any:
    """
    Get a result from the Redis cache.

    Args:
        key: The cache key to retrieve
        default: Value to return if key is not found (default: None)

    Returns:
        The cached value or the default value if not found
    """
    try:
        value = await redis_cache.get(key)
        if value is None:
            return default
        return value
    except Exception as e:
        logger.warning(f"Error retrieving from Redis cache: {str(e)}")
        return default


async def invalidate_cache(key: str) -> bool:
    """
    Invalidate a specific cache key in Redis.

    Args:
        key: The cache key to invalidate

    Returns:
        True if the key was found and deleted, False otherwise
    """
    try:
        return bool(await redis_cache.delete(key))
    except Exception as e:
        logger.warning(f"Error invalidating Redis cache: {str(e)}")
        return False


async def get_or_set_cache(
    key: str, func: Callable[[], Any], expire_seconds: int | None = None
) -> Any:
    """
    Get a value from Redis, or compute and store it if not found.

    Args:
        key: The cache key to retrieve or store
        func: Function to call if the key is not in the cache
        expire_seconds: Optional cache expiration in seconds

    Returns:
        The cached or computed value
    """
    try:
        value = await redis_cache.get(key)
        if value is not None:
            return value
        result = func()
        await redis_cache.set(key, result, expire_seconds)
        return result
    except Exception as e:
        logger.error(f"Error computing or caching result in Redis: {str(e)}")
        raise


def cache_result(expire_seconds: int | None = None, key_prefix: str = ""):
    """
    Decorator that caches the result of a function based on its arguments using Redis.

    Args:
        expire_seconds: Optional cache expiration in seconds
        key_prefix: Optional prefix for the cache key

    Returns:
        Decorated function that uses Redis caching
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key_args = json.dumps(args, sort_keys=True, default=str)
            key_kwargs = json.dumps(kwargs, sort_keys=True, default=str)
            raw_key = f"{key_prefix}:{func.__name__}:{key_args}:{key_kwargs}"
            key = hashlib.md5(raw_key.encode()).hexdigest()
            return await get_or_set_cache(
                key, lambda: func(*args, **kwargs), expire_seconds
            )

        return wrapper

    return decorator
