"""
Shared pytest fixtures and configuration for Redis tests
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.core.redis.client import RedisClient
from app.core.redis.config import RedisConfig
from app.core.redis.rate_limit import check_rate_limit
from app.core.redis.redis_cache import RedisCache


@pytest.fixture
def mock_redis_client():
    """Mocked RedisClient instance with patched execute_command"""
    with patch('redis.asyncio.cluster.RedisCluster'):
        client = RedisClient()
        mock_execute = AsyncMock()
        client._client.execute_command = mock_execute
        yield client, mock_execute

@pytest.fixture
def redis_cache():
    """Pre-configured RedisCache instance"""
    cache = RedisCache()
    yield cache
    # Cleanup any test data
    asyncio.run(cache.clear_namespace("test_"))


@pytest.fixture
def rate_limit_checker():
    """Rate limit checker function with default values"""

    async def checker(endpoint, identifier, limit=10, window=60):
        return await check_rate_limit(endpoint, identifier, limit, window)

    return checker


@pytest.fixture(autouse=True)
def reset_redis_config():
    """Reset RedisConfig between tests"""
    original = RedisConfig.__dict__.copy()
    yield
    RedisConfig.__dict__.clear()
    RedisConfig.__dict__.update(original)


@pytest.fixture
def mock_time():
    """Mock time module for time-sensitive tests"""
    with patch("time.time") as mock_time:
        mock_time.return_value = 0
        yield mock_time
