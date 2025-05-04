"""
Redis client initialization and configuration.

Follows best practices for:
- Connection pooling
- Timeout handling
- Error recovery
- Sharding support
"""

import asyncio
import json
import logging
from typing import Any

from circuitbreaker import circuit
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from prometheus_client import Counter, Gauge, Histogram
from redis.asyncio import Redis, RedisCluster
from redis.exceptions import RedisError, TimeoutError

from app.core.redis.config import RedisConfig

REDIS_CLUSTER = RedisConfig.REDIS_CLUSTER
REDIS_DB = RedisConfig.REDIS_DB
REDIS_FAILURE_THRESHOLD = RedisConfig.REDIS_FAILURE_THRESHOLD
REDIS_HOST = RedisConfig.REDIS_HOST
REDIS_MAX_CONNECTIONS = RedisConfig.REDIS_MAX_CONNECTIONS
REDIS_PASSWORD = RedisConfig.REDIS_PASSWORD
REDIS_PORT = RedisConfig.REDIS_PORT
REDIS_RECOVERY_TIMEOUT = RedisConfig.REDIS_RECOVERY_TIMEOUT
REDIS_SOCKET_CONNECT_TIMEOUT = RedisConfig.REDIS_SOCKET_CONNECT_TIMEOUT
REDIS_SOCKET_TIMEOUT = RedisConfig.REDIS_SOCKET_TIMEOUT
# Security and advanced config
REDIS_SSL = getattr(RedisConfig, "REDIS_SSL", False)
REDIS_SSL_CERT_REQS = getattr(RedisConfig, "REDIS_SSL_CERT_REQS", None)
REDIS_SSL_CA_CERTS = getattr(RedisConfig, "REDIS_SSL_CA_CERTS", None)
REDIS_SSL_KEYFILE = getattr(RedisConfig, "REDIS_SSL_KEYFILE", None)
REDIS_SSL_CERTFILE = getattr(RedisConfig, "REDIS_SSL_CERTFILE", None)
REDIS_PROTOCOL = getattr(RedisConfig, "REDIS_PROTOCOL", 2)
REDIS_USERNAME = getattr(RedisConfig, "REDIS_USERNAME", None)
REDIS_URL = getattr(RedisConfig, "REDIS_URL", None)

logger = logging.getLogger(__name__)

# Default timeout constants (in seconds)
DEFAULT_CONNECTION_TIMEOUT = 5.0
DEFAULT_SOCKET_TIMEOUT = 10.0
DEFAULT_COMMAND_TIMEOUT = 5.0

# Prometheus metrics
SHARD_SIZE_GAUGE = Gauge(
    'redis_shard_size_bytes',
    'Size of Redis shards in bytes',
    ['shard']
)
SHARD_OPS_GAUGE = Gauge(
    'redis_shard_ops_per_sec',
    'Operations per second per shard',
    ['shard']
)
REQUEST_DURATION = Histogram(
    'redis_request_duration_seconds',
    'Redis request duration',
    ['operation', 'shard']
)
ERROR_COUNTER = Counter(
    'redis_errors_total',
    'Total Redis errors',
    ['error_type', 'shard']
)

tracer = trace.get_tracer(__name__)


class RedisClient:
    """
    Redis client wrapper with connection management and utilities.

    Handles:
    - Connection pooling
    - Automatic reconnections
    - Timeout handling
    - Sharding support
    """

    def __init__(self):
        """Initialize with automatic cluster detection"""
        self._client = None
        self._cluster_mode = REDIS_CLUSTER
        self._metrics_task = None

    async def get_client(self) -> Redis | RedisCluster:
        """
        Returns configured client based on settings
        - Auto-reconnects if needed
        - Supports both cluster and sharded modes
        """
        if self._cluster_mode:
            return await self._get_cluster_client()
        return await self._get_sharded_client()

    async def _get_cluster_client(self) -> RedisCluster:
        """Get a cluster Redis client based on configuration"""
        if not self._client:
            if REDIS_URL:
                self._client = RedisCluster.from_url(
                    REDIS_URL,
                    ssl=REDIS_SSL,
                    ssl_cert_reqs=REDIS_SSL_CERT_REQS,
                    ssl_ca_certs=REDIS_SSL_CA_CERTS,
                    ssl_keyfile=REDIS_SSL_KEYFILE,
                    ssl_certfile=REDIS_SSL_CERTFILE,
                    protocol=REDIS_PROTOCOL,
                    username=REDIS_USERNAME,
                    password=REDIS_PASSWORD,
                    db=REDIS_DB,
                    max_connections=REDIS_MAX_CONNECTIONS,
                    socket_timeout=REDIS_SOCKET_TIMEOUT,
                    socket_connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT,
                )
            else:
                self._client = RedisCluster(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    username=REDIS_USERNAME,
                    password=REDIS_PASSWORD,
                    db=REDIS_DB,
                    ssl=REDIS_SSL,
                    ssl_cert_reqs=REDIS_SSL_CERT_REQS,
                    ssl_ca_certs=REDIS_SSL_CA_CERTS,
                    ssl_keyfile=REDIS_SSL_KEYFILE,
                    ssl_certfile=REDIS_SSL_CERTFILE,
                    protocol=REDIS_PROTOCOL,
                    max_connections=REDIS_MAX_CONNECTIONS,
                    socket_timeout=REDIS_SOCKET_TIMEOUT,
                    socket_connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT,
                )
        return self._client

    async def _get_sharded_client(self) -> RedisCluster:
        """Get a Redis client configured for sharded mode"""
        from redis.asyncio.cluster import RedisCluster
        if REDIS_URL:
            return RedisCluster.from_url(
                REDIS_URL,
                ssl=REDIS_SSL,
                ssl_cert_reqs=REDIS_SSL_CERT_REQS,
                ssl_ca_certs=REDIS_SSL_CA_CERTS,
                ssl_keyfile=REDIS_SSL_KEYFILE,
                ssl_certfile=REDIS_SSL_CERTFILE,
                protocol=REDIS_PROTOCOL,
                username=REDIS_USERNAME,
                password=REDIS_PASSWORD,
                db=REDIS_DB,
                max_connections=REDIS_MAX_CONNECTIONS,
                socket_timeout=REDIS_SOCKET_TIMEOUT,
                socket_connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT,
                decode_responses=True
            )
        return RedisCluster(
            startup_nodes=[
                {"host": REDIS_HOST, "port": REDIS_PORT}
            ],
            username=REDIS_USERNAME,
            password=REDIS_PASSWORD,
            db=REDIS_DB,
            ssl=REDIS_SSL,
            ssl_cert_reqs=REDIS_SSL_CERT_REQS,
            ssl_ca_certs=REDIS_SSL_CA_CERTS,
            ssl_keyfile=REDIS_SSL_KEYFILE,
            ssl_certfile=REDIS_SSL_CERTFILE,
            protocol=REDIS_PROTOCOL,
            max_connections_per_node=REDIS_MAX_CONNECTIONS,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT,
            decode_responses=True
        )

    async def shutdown(self):
        """Cleanly shutdown Redis client"""
        if self._client:
            await self._client.close()
            self._client = None
        if self._metrics_task:
            self._metrics_task.cancel()

    async def __aenter__(self):
        if not await self.is_healthy():
            raise ConnectionError("Redis connection failed")
        self._metrics_task = asyncio.create_task(self._update_metrics())

    @circuit(
        failure_threshold=REDIS_FAILURE_THRESHOLD,
        recovery_timeout=REDIS_RECOVERY_TIMEOUT,
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
        failure_threshold=REDIS_FAILURE_THRESHOLD,
        recovery_timeout=REDIS_RECOVERY_TIMEOUT,
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

    async def _update_metrics(self):
        """Periodically update Redis metrics"""
        while True:
            try:
                client = await self.get_client()
                info = await client.info('all')
                
                for shard, stats in info.items():
                    SHARD_SIZE_GAUGE.labels(shard=shard).set(stats.get('used_memory', 0))
                    SHARD_OPS_GAUGE.labels(shard=shard).set(stats.get('instantaneous_ops_per_sec', 0))
                    
            except Exception as e:
                ERROR_COUNTER.labels(error_type=str(type(e).__name__), shard='unknown').inc()
                logger.error(f"Metrics update failed: {e}")
            
            await asyncio.sleep(60)  # Update every minute

    async def incr(self, key: str, timeout: float = DEFAULT_COMMAND_TIMEOUT) -> int:
        """Increment a key's integer value by 1. Returns new value."""
        with tracer.start_as_current_span("redis.incr") as span:
            span.set_attribute("redis.key", key)
            try:
                value = await (await self.get_client()).incr(key)
                span.set_status(StatusCode.OK)
                return value
            except Exception as e:
                span.record_exception(e)
                span.set_status(StatusCode.ERROR)
                raise

    async def expire(self, key: str, ex: int, timeout: float = DEFAULT_COMMAND_TIMEOUT) -> bool:
        """Set a key's time to live in seconds."""
        with tracer.start_as_current_span("redis.expire") as span:
            span.set_attribute("redis.key", key)
            span.set_attribute("redis.ttl", ex)
            try:
                result = await (await self.get_client()).expire(key, ex)
                span.set_status(StatusCode.OK)
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(StatusCode.ERROR)
                raise

    async def ttl(self, key: str, timeout: float = DEFAULT_COMMAND_TIMEOUT) -> int:
        """Get the time to live (in seconds) of a key."""
        with tracer.start_as_current_span("redis.ttl") as span:
            span.set_attribute("redis.key", key)
            try:
                value = await (await self.get_client()).ttl(key)
                span.set_status(StatusCode.OK)
                return value
            except Exception as e:
                span.record_exception(e)
                span.set_status(StatusCode.ERROR)
                raise

    async def exists(self, key: str, timeout: float = DEFAULT_COMMAND_TIMEOUT) -> bool:
        """Check if a key exists in Redis (returns True if exists)."""
        with tracer.start_as_current_span("redis.exists") as span:
            span.set_attribute("redis.key", key)
            try:
                exists = await (await self.get_client()).exists(key)
                span.set_status(StatusCode.OK)
                return exists == 1
            except Exception as e:
                span.record_exception(e)
                span.set_status(StatusCode.ERROR)
                raise


# Singleton Redis client instance
client = RedisClient()

# Module-level functions for convenience
get_client = client.get_client
shutdown = client.shutdown
get = client.get
set = client.set
delete = client.delete
is_healthy = client.is_healthy
incr = client.incr
expire = client.expire
ttl = client.ttl
exists = client.exists
