"""
Redis cache consistency tests
"""
import asyncio
from unittest.mock import patch

import pytest

from app.core.redis.redis_cache import RedisCache


@pytest.mark.asyncio
async def test_cache_invalidation():
    """Test cache invalidation works"""
    cache = RedisCache()
    await cache.set("test_key", "value", ttl=10)
    await cache.invalidate("test_key")
    assert await cache.get("test_key") is None

@pytest.mark.asyncio
async def test_ttl_behavior():
    """Verify TTL expiration works"""
    cache = RedisCache()
    await cache.set("ttl_key", "value", ttl=1)
    assert await cache.get("ttl_key") == "value"
    await asyncio.sleep(1.1)
    assert await cache.get("ttl_key") is None

@pytest.mark.asyncio
async def test_race_conditions():
    """Test cache stampede protection"""
    cache = RedisCache()
    results = await asyncio.gather(
        *[cache.get_or_set("race_key", lambda: "value") for _ in range(10)]
    )
    assert all(r == "value" for r in results)
