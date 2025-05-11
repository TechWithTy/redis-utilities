"""
Shared pytest fixtures and configuration for Redis tests
"""

import asyncio
import subprocess
import sys
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.core.redis.client import RedisClient
from app.core.redis.config import RedisConfig
from app.core.redis.rate_limit import check_rate_limit
from app.core.redis.redis_cache import RedisCache


@pytest.fixture(scope="session", autouse=True)
def ensure_redis_container():
    """
    Ensure the Redis Docker container is running for integration tests.
    If not running, start it using docker-compose.redis.yml.
    """
    import logging
    import os
    docker_compose = os.path.join(os.path.dirname(__file__), '../docker/docker-compose.redis.yml')
    container_name = "redis"
    try:
        # Check if container is running
        ps = subprocess.run(["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"], capture_output=True, text=True)
        running = container_name in ps.stdout
        if not running:
            logging.info("[pytest] Redis container not running, starting via docker-compose...")
            subprocess.run(["docker-compose", "-f", docker_compose, "up", "-d", "redis"], check=True)
            # Wait for container to be healthy (ping)
            for _ in range(20):
                health = subprocess.run(["docker", "inspect", "--format", "{{.State.Health.Status}}", container_name], capture_output=True, text=True)
                if "healthy" in health.stdout:
                    break
                time.sleep(2)
            else:
                raise RuntimeError("Redis container did not become healthy in time.")
        else:
            logging.info("[pytest] Redis container already running.")
    except Exception as e:
        logging.warning(f"[pytest] Could not ensure Redis container is running: {e}")
    yield


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
    original_attrs = {k: v for k, v in vars(RedisConfig).items() if not k.startswith('__')}
    yield
    # Restore only the attributes that were present originally
    for k in list(vars(RedisConfig).keys()):
        if not k.startswith('__'):
            if k in original_attrs:
                setattr(RedisConfig, k, original_attrs[k])
            else:
                delattr(RedisConfig, k)


@pytest.fixture
def mock_time():
    """Mock time module for time-sensitive tests"""
    with patch("time.time") as mock_time:
        mock_time.return_value = 0
        yield mock_time
