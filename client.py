"""
Redis client initialization and configuration.

Follows best practices for:
- Connection pooling
- Timeout handling
- Error recovery
"""

import json
import logging
from typing import Any

from circuitbreaker import circuit
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from redis.asyncio import Redis, RedisCluster
from redis.exceptions import RedisError, TimeoutError

from app.core.config import settings
from app.core.redis.config import RedisConfig

logger = logging.getLogger(__name__)

# Default timeout constants (in seconds)
DEFAULT_CONNECTION_TIMEOUT = 5.0
DEFAULT_SOCKET_TIMEOUT = 10.0
DEFAULT_COMMAND_TIMEOUT = 5.0

tracer = trace.get_tracer(__name__)


class RedisClient:
    """
    Redis client wrapper with connection management and utilities.

    Handles:
    - Connection pooling
    - Automatic reconnections
    - Timeout handling
    """

    def __init__(self):
        """Initialize with automatic cluster detection"""
        self._client = None
        self._cluster_mode = getattr(settings, "REDIS_CLUSTER", False)

    async def get_client(self) -> Redis | RedisCluster:
        """
        Returns configured client based on settings
        - Auto-reconnects if needed
        - Handles both cluster and standalone modes
        """
        if not self._client:
            if self._cluster_mode:
                self._client = RedisCluster(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    socket_timeout=RedisConfig.REDIS_SOCKET_TIMEOUT,
                    socket_connect_timeout=RedisConfig.REDIS_SOCKET_CONNECT_TIMEOUT,
                    max_connections=RedisConfig.REDIS_MAX_CONNECTIONS
                )
            else:
                self._client = Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    socket_timeout=RedisConfig.REDIS_SOCKET_TIMEOUT,
                    socket_connect_timeout=RedisConfig.REDIS_SOCKET_CONNECT_TIMEOUT,
                    max_connections=RedisConfig.REDIS_MAX_CONNECTIONS
                )
        return self._client

    async def shutdown(self):
        """Cleanly shutdown Redis client"""
        if self._client:
            await self._client.close()
            self._client = None

    async def __aenter__(self):
        if not await self.is_healthy():
            raise ConnectionError("Redis connection failed")

    @circuit(
        failure_threshold=getattr(settings, "REDIS_FAILURE_THRESHOLD", 3),
        recovery_timeout=getattr(settings, "REDIS_RECOVERY_TIMEOUT", 30),
        expected_exception=(RedisError, TimeoutError),
        fallback_function=lambda e: logger.warning(f"Circuit open: {str(e)}"),
    )
    async def get(self, key: str, timeout: float = DEFAULT_COMMAND_TIMEOUT) -> Any:
        """Get value with tracing"""
        with tracer.start_as_current_span("redis.get") as span:
            span.set_attribute("redis.key", key)
            try:
                value = await (await self.get_client()).get(key, timeout=timeout)
                span.set_status(StatusCode.OK)
                return json.loads(value) if value else None
            except Exception as e:
                span.record_exception(e)
                span.set_status(StatusCode.ERROR)
                raise

    @circuit(
        failure_threshold=getattr(settings, "REDIS_FAILURE_THRESHOLD", 3),
        recovery_timeout=getattr(settings, "REDIS_RECOVERY_TIMEOUT", 30),
        expected_exception=(RedisError, TimeoutError),
    )
    async def set(
        self,
        key: str,
        value: Any,
        ex: int | None = None,
        timeout: float = DEFAULT_COMMAND_TIMEOUT,
    ) -> bool:
        """Set value with tracing"""
        with tracer.start_as_current_span("redis.set") as span:
            span.set_attributes({"redis.key": key, "redis.ttl": ex or 0})
            try:
                result = await (await self.get_client()).set(
                    key, json.dumps(value), ex=ex, timeout=timeout
                )
                span.set_status(StatusCode.OK)
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(StatusCode.ERROR)
                raise

    async def delete(self, *keys: str, timeout: float = DEFAULT_COMMAND_TIMEOUT) -> int:
        """Delete one or more keys from Redis with timeout"""
        try:
            return await (await self.get_client()).delete(*keys, timeout=timeout)
        except (RedisError, TimeoutError) as e:
            logger.error(f"Redis delete failed for keys {keys}: {str(e)}")
            raise

    async def is_healthy(self) -> bool:
        """Check if Redis connection is healthy"""
        try:
            return await (await self.get_client()).ping()
        except (RedisError, TimeoutError):
            return False


# Singleton Redis client instance
client = RedisClient()

# Module-level functions for convenience
get_client = client.get_client
shutdown = client.shutdown
get = client.get
set = client.set
delete = client.delete
is_healthy = client.is_healthy
